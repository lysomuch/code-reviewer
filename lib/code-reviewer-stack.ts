import * as cdk from 'aws-cdk-lib';
import { SnsEventSource, SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { Construct } from 'constructs';
import { CRBucket  } from './bucket-stack';
import { CRDatabase } from './database-stack';
import { CRSqs } from './sqs-stack';
import { CRSns } from './sns-stack';
import { CRApi } from './api-stack';

export class CodeReviewerStack extends cdk.Stack {
	constructor(scope: Construct, id: string, props?: cdk.StackProps) {
		super(scope, id, props);

		const project_name = new cdk.CfnParameter(this, 'ProjectName', {
			type: 'String',
			default: 'aws-code-reviewer',
			description: 'Name of the project. Use only English letters, numbers, hyphens and underscores. All cloud resource names will be prefixed with this. For example, if ProjectName="a-b-c", then the resource prefix will be a-b-c-',
		});
		const prefix = project_name.valueAsString

		const smtp_server = new cdk.CfnParameter(this, 'SMTPServer', {
			type: 'String',
			default: '',
			description: '[Optional] SMTP server. If provided, it will be used to send Code Review Report.',
		});
		const smtp_port = new cdk.CfnParameter(this, 'SMTPPort', {
			type: 'String',
			default: '',
			description: '[Optional] SMTP port. If provided, it will be used to send Code Review Report.',
		});
		const smtp_username = new cdk.CfnParameter(this, 'SMTPUsername', {
			type: 'String',
			default: '',
			description: '[Optional] SMTP username. If provided, it will be used to send Code Review Report.',
		});
		const smtp_password = new cdk.CfnParameter(this, 'SMTPPassword', {
			type: 'String',
			default: '',
			description: '[Optional] SMTP password. If provided, it will be used to send Code Review Report.',
		});
		const report_sender = new cdk.CfnParameter(this, 'ReportSender', {
			type: 'String',
			default: '',
			description: '[Optional] Report sender, an email address. If provided, it will be used to send Code Review Report.',
		});
		const report_receiver = new cdk.CfnParameter(this, 'ReportReceiver', {
			type: 'String',
			default: '',
			description: '[Optional] Report receiver, an email address. If provided, it will be used to receive Code Review Report.',
		});

		/* 创建必要的S3 Buckets */
		const buckets = new CRBucket(this, 'Buckets', { account: this.account, region: this.region, prefix: prefix })

		/* 创建任务队列SQS */
		const sqs = new CRSqs(this, 'TaskSQS', { prefix: prefix })

		/* 创建Report SNS，并让Emails订阅SNS */
		const sns = new CRSns(this, 'ReportSNS', { prefix: prefix })

		/* 数据库 */
		const database = new CRDatabase(this, 'Database', { prefix: prefix })

		/* API */
		const api = new CRApi(this, 'API', { prefix: prefix, rule_table: database.rule_table })
		
		/* 配置环境变量 */
		api.data_initializer.addEnvironment('RULE_TABLE', database.rule_table.tableName)
		api.data_initializer.addEnvironment('REPOSITORY_TABLE', database.repo_table.tableName)

		api.request_handler.addEnvironment('REQUEST_TABLE', database.request_table.tableName)
		api.request_handler.addEnvironment('REPOSITORY_TABLE', database.repo_table.tableName)
		api.request_handler.addEnvironment('TASK_DISPATCHER_FUN_NAME', api.task_dispatcher.functionName)
		
		api.task_dispatcher.addEnvironment('REQUEST_TABLE', database.request_table.tableName)
		api.task_dispatcher.addEnvironment('RULE_TABLE', database.rule_table.tableName)
		api.task_dispatcher.addEnvironment('TASK_SQS_URL', sqs.task_queue.queueUrl)

		api.task_executor.addEnvironment('BUCKET_NAME', buckets.report_bucket.bucketName)
		api.task_executor.addEnvironment('REQUEST_TABLE', database.request_table.tableName)
		api.task_executor.addEnvironment('RULE_TABLE', database.rule_table.tableName)
		api.task_executor.addEnvironment('TASK_TABLE', database.task_table.tableName)
		api.task_executor.addEnvironment('TASK_SQS_URL', sqs.task_queue.queueUrl)
		api.task_executor.addEnvironment('SNS_TOPIC_ARN', sns.report_topic.topicArn)
		api.task_executor.addEnvironment('SQS_MAX_RETRIES', '5')
		api.task_executor.addEnvironment('SQS_BASE_DELAY', '2')
		api.task_executor.addEnvironment('SQS_MAX_DELAY', '60')
		api.task_executor.addEnvironment('TEMPERATURE', '0')
		api.task_executor.addEnvironment('TOP_P', '0.5')
		api.task_executor.addEnvironment('MAX_TOKEN_TO_SAMPLE', '10000')
		api.task_executor.addEnvironment('MAX_FAILED_TIMES', '6')
		api.task_executor.addEnvironment('REPORT_TIMEOUT_SECONDS', '900')

		api.report_receiver.addEnvironment('SMTP_SERVER', smtp_server.valueAsString)
		api.report_receiver.addEnvironment('SMTP_PORT', smtp_port.valueAsString)
		api.report_receiver.addEnvironment('SMTP_USERNAME', smtp_username.valueAsString)
		api.report_receiver.addEnvironment('SMTP_PASSWORD', smtp_password.valueAsString)
		api.report_receiver.addEnvironment('REPORT_SENDER', report_sender.valueAsString)
		api.report_receiver.addEnvironment('REPORT_RECEIVER', report_receiver.valueAsString)

		/* 触发Lambda */
		api.task_executor.addEventSource(new SqsEventSource(sqs.task_queue))
		api.report_receiver.addEventSource(new SnsEventSource(sns.report_topic))

		/* 权限配置 */
		buckets.report_bucket.grantReadWrite(api.task_executor)
		
		database.repo_table.grantReadWriteData(api.request_handler)
		
		database.request_table.grantReadWriteData(api.request_handler)
		database.request_table.grantReadWriteData(api.task_dispatcher)
		database.request_table.grantReadWriteData(api.task_executor)

		database.repo_table.grantReadData(api.request_handler)
		database.repo_table.grantWriteData(api.data_initializer)
		database.rule_table.grantWriteData(api.data_initializer)
		database.rule_table.grantReadData(api.task_dispatcher)

		database.task_table.grantReadWriteData(api.task_executor)
		
		sqs.task_queue.grantSendMessages(api.task_dispatcher)
		sqs.task_queue.grantSendMessages(api.task_executor)
		sqs.task_queue.grantConsumeMessages(api.task_executor)
		
		sns.report_topic.grantPublish(api.task_executor)

		/* Output Section */
		new cdk.CfnOutput(this, 'Endpoint', {
			value: `https://${api.api.restApiId}.execute-api.${this.region}.amazonaws.com/prod/codereview`,
		})
		new cdk.CfnOutput(this, 'ApiKeyId', {
			value: api.api_key.keyId,
			description: `API Key ID for Code Review API.`
		})
		new cdk.CfnOutput(this, 'HowToGetApiKeyValue', {
			value: 'aws apigateway get-api-key --include-value --output text --query \'value\' --api-key {ApiKeyId}',
			description: 'Execute this command to get the API Key value, replacing {ApiKeyId} with the actual value.'
		})
		
	}

}
