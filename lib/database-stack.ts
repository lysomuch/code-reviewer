import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as cfnres from 'aws-cdk-lib/aws-cloudfront';


export class CRDatabase extends Construct {
  
	public readonly request_table: dynamodb.Table;
	public readonly task_table: dynamodb.Table;
	public readonly repo_table: dynamodb.Table;
	public readonly rule_table: dynamodb.Table;

	constructor(scope: Construct, id: string, props: { prefix: string }) {
		super(scope, id);

		/*  Repository Table */
		this.repo_table = new dynamodb.Table(this, 'RepositoryTable', {
			tableName: `${props.prefix}-repository`,
			partitionKey: { name: 'repository_url', type: dynamodb.AttributeType.STRING },
			sortKey: { name: 'branch_regexp', type: dynamodb.AttributeType.STRING },
			billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
			encryption: dynamodb.TableEncryption.AWS_MANAGED,
			stream: dynamodb.StreamViewType.NEW_IMAGE,
			pointInTimeRecovery: true,
		})

		/*  Request Table */
		this.request_table = new dynamodb.Table(this, 'RequestTable', {
			tableName: `${props.prefix}-request`,
			partitionKey: { name: 'commit_id', type: dynamodb.AttributeType.STRING },
			sortKey: { name: 'request_id', type: dynamodb.AttributeType.STRING},
			billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
			encryption: dynamodb.TableEncryption.AWS_MANAGED,
			stream: dynamodb.StreamViewType.NEW_IMAGE,
			pointInTimeRecovery: true,
		})

		/* Task Table */
		this.task_table = new dynamodb.Table(this, 'TaskTable', {
			tableName: `${props.prefix}-task`,
			partitionKey: { name: 'request_id', type: dynamodb.AttributeType.STRING },
			sortKey: { name: 'number', type: dynamodb.AttributeType.NUMBER },
			billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
			encryption: dynamodb.TableEncryption.AWS_MANAGED,
			stream: dynamodb.StreamViewType.NEW_IMAGE,
			pointInTimeRecovery: true,
		})

		/* Regulation Table */
		this.rule_table = new dynamodb.Table(this, 'RuleTable', {
			tableName: `${props.prefix}-rule`,
			partitionKey: { name: 'mode', type: dynamodb.AttributeType.STRING },
			sortKey: { name: 'number', type: dynamodb.AttributeType.NUMBER },
			billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
			encryption: dynamodb.TableEncryption.AWS_MANAGED,
			stream: dynamodb.StreamViewType.NEW_IMAGE,
			pointInTimeRecovery: true,
		})
		
	}

}
