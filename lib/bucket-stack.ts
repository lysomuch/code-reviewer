import { Construct } from 'constructs';
import { Bucket, BucketEncryption, BlockPublicAccess } from 'aws-cdk-lib/aws-s3';

export class CRBucket extends Construct {
	public readonly report_bucket: Bucket;

	constructor(scope: Construct, id: string, props: { account: string; region: string; prefix: string }) {
		super(scope, id);

		// 创建访问日志存储桶
		const access_logs_bucket = new Bucket(this, 'AccessLogsBucket', {
			bucketName: `${props.prefix}-logs-${props.account}-${props.region}`,
			encryption: BucketEncryption.S3_MANAGED,
			blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
			enforceSSL: true,
			versioned: true,
		});

		// 创建主要存储桶
		this.report_bucket = new Bucket(this, 'CodeReviewBucket', {
			bucketName: `${props.prefix}-report-${props.account}-${props.region}`,
			encryption: BucketEncryption.S3_MANAGED,
			blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
			enforceSSL: true,
			versioned: true,
			serverAccessLogsBucket: access_logs_bucket,
			serverAccessLogsPrefix: 'logs/',
		});
	}
}