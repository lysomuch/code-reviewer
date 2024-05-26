import * as cdk from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as iam from 'aws-cdk-lib/aws-iam';

import { Construct } from 'constructs';

export class CRApi extends Construct {
	
	// public readonly bucket: Bucket;
	public data_initializer: lambda.Function
	public readonly request_handler: lambda.Function
	public readonly task_dispatcher: lambda.Function
	public readonly task_executor: lambda.Function
	public readonly report_receiver: lambda.Function
	public readonly api: apigateway.RestApi
	public readonly api_key: apigateway.ApiKey
	public readonly root_resource: apigateway.Resource

	constructor(scope: Construct, id: string, props: { prefix: string; rule_table: dynamodb.Table }) {
		super(scope, id);

		const layer = new lambda.LayerVersion(this, 'LayerVersion', {
			code: lambda.Code.fromAsset('layer/layer.zip'),
			compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
			description: 'This layer includes pyyaml, python-gitlab module.',
		})

		/* 处理Request的Lambda */
		this.request_handler = new lambda.Function(this, 'RequestHandler', {
			functionName: `${props.prefix}-request-handler`,
			runtime: lambda.Runtime.PYTHON_3_11,
			code: lambda.Code.fromAsset('lambda'),
			handler: 'request_handler.lambda_handler',
			timeout: cdk.Duration.seconds(30),
			layers: [ layer ],
		})
		
		/* Bedrock任务分派的Lambda */
		this.task_dispatcher = new lambda.Function(this, 'TaskDispatcher', {
			functionName: `${props.prefix}-task-dispatcher`,
			runtime: lambda.Runtime.PYTHON_3_11,
			code: lambda.Code.fromAsset('lambda'),
			handler: 'task_dispatcher.lambda_handler',
			timeout: cdk.Duration.seconds(60 * 15),
			layers: [ layer ],
		})
		this.task_dispatcher.grantInvoke(this.request_handler)

		/* Bedrock任务执行的Lambda */
		this.task_executor = new lambda.Function(this, 'TaskExecutor', {
			functionName: `${props.prefix}-task-executor`,
			runtime: lambda.Runtime.PYTHON_3_11,
			code: lambda.Code.fromAsset('lambda'),
			handler: 'task_executor.lambda_handler',
			timeout: cdk.Duration.seconds(60 * 15),
			layers: [ layer ],
		})
		const bedrock_policy = new iam.PolicyStatement({
            actions: ["bedrock:InvokeModel"],
            resources: ["*"],
        })
		this.task_executor.role?.addToPrincipalPolicy(bedrock_policy)

		/* 接受报告的Lambda */
		this.report_receiver = new lambda.Function(this, 'ReportReceiver', {
			functionName: `${props.prefix}-report-receiver`,
			runtime: lambda.Runtime.PYTHON_3_11,
			code: lambda.Code.fromAsset('lambda'),
			handler: 'report_receiver.lambda_handler',
			timeout: cdk.Duration.seconds(30),
			layers: [ layer ],
		})
		
		/* 创建 API Key */
		this.api_key = new apigateway.ApiKey(this, 'CodeReviewApiKey', {
			apiKeyName: `${props.prefix}-api-key`,
			description: 'API Key for Code Review API',
		})
		
		/* 创建 API Gateway REST API */
		this.api = new apigateway.RestApi(this, 'API', {
			restApiName: `${props.prefix}-api`,
			description: 'API Gateway for code view',
			deployOptions: {
				stageName: 'prod',
				loggingLevel: apigateway.MethodLoggingLevel.INFO,
				dataTraceEnabled: true
			},
			cloudWatchRole: true,
			// policy: cloud_watch_logs_policy
		})
	
		/* 创建 API Gateway 资源和方法 */
		this.root_resource = this.api.root.addResource('codereview');
		const method = this.root_resource.addMethod('POST', new apigateway.LambdaIntegration(this.request_handler, { 
			timeout: cdk.Duration.seconds(29) 
		}), { 
			apiKeyRequired: true 
		})

		/* 创建UsagePlan */
		const plan = this.api.addUsagePlan('CodeReviewerUsagePlan', {
			name: `${props.prefix}-usage-plan`,
			throttle: {
			  rateLimit: 100,
			  burstLimit: 100
			}
		})
		plan.addApiKey(this.api_key)
		plan.addApiStage({
			stage: this.api.deploymentStage,
		})

		/* Initialize rule data */
		this.init_data(props)
		
	}

	init_data(props: { prefix: string; rule_table: dynamodb.Table}): void {

		this.data_initializer = new lambda.Function(this, 'DataInitializer', {
			functionName: `${props.prefix}-data-initializer`,
			runtime: lambda.Runtime.PYTHON_3_11,
			code: lambda.Code.fromAsset('lambda'),
			handler: 'data_initializer.lambda_handler',
		})

		// 创建自定义资源
		const customResource = new cr.AwsCustomResource(this, 'CustomResource', {
			onUpdate: {
				service: 'Lambda',
				action: 'invoke',
				parameters: {
					FunctionName: this.data_initializer.functionName,
					Payload: JSON.stringify({ message: 'CloudFormation stack updated' }),
				},
				physicalResourceId: cr.PhysicalResourceId.of('CustomResourceId'),
			},
			onCreate: {
				service: 'Lambda',
				action: 'invoke',
				parameters: {
					FunctionName: this.data_initializer.functionName,
					Payload: JSON.stringify({ message: 'CloudFormation stack created' }),
				},
				physicalResourceId: cr.PhysicalResourceId.of('CustomResourceId'),
			},
			policy: cr.AwsCustomResourcePolicy.fromStatements([
				new iam.PolicyStatement({
				  actions: ['lambda:InvokeFunction'],
				  resources: [this.data_initializer.functionArn],
				}),
			]),
		})

		// 确保 Lambda 函数在自定义资源之前创建
		customResource.node.addDependency(this.data_initializer);

	}

}
