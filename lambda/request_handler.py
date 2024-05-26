import traceback
import json, os, re, datetime
import boto3, base, yaml
import codelib

REQUEST_TABLE 				= os.getenv('REQUEST_TABLE')
REPOSITORY_TABLE 			= os.getenv('REPOSITORY_TABLE')
TASK_DISPATCHER_FUN_NAME 	= os.getenv('TASK_DISPATCHER_FUN_NAME')
	
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
sqs_client = boto3.client('sqs')

def parse_target(variables):
	target = variables.get('target')
	if target: return target

	targets = variables.get('targets')
	if isinstance(targets, list):
		return ', '.join(targets)
	else:
		return targets if targets else '**'
	
def parse_process_mode(params):
	
	web_url = params.get('web_url')
	target_branch = params.get('target_branch')
	event_type = params.get('event_type')

	response = dynamodb.Table(REPOSITORY_TABLE).query(
		KeyConditionExpression='repository_url=:ru',
		ExpressionAttributeValues={ ':ru': web_url }
	)

	records = []
	for record in response['Items']:
		branch_regexp = record.get('branch_regexp')
		if re.match(branch_regexp, target_branch):
			records.append(record)

	for record in records:
		print('Found {} repository configurations, use the first one: {}'.format(len(records), base.dump_json(record)))
		result = {}
		for key, value in record.items():
			if key.startswith('event_'):
				result[key[6:]] = value
		mode = result.get(event_type)
		print(f'Parsed code review mode({mode}) for branch({target_branch}) by configuration {record}')
		return mode
	
	print(f'Can\'t parse any code review mode for branch({target_branch}) for no any repository configuration matched.')
	return None

def lambda_handler(event, context):
	
	print('Event:', base.dump_json(event))
	current_time = datetime.datetime.now()
	
	try:
		
		# 解析Gitlab参数
		params = codelib.parse_parameters(event)
		print('Request identifier:', params['request_id'])
		print('Project={project_id}({project_name}), Commit={commit_id}, Ref={ref}'.format(**params))
		print('Repository URL={repo_url}, Private Token={private_token}'.format(**params))

		if not params['commit_id']:
			print(f'COMMID ID is not found, skip the processing.')
			return { 'statusCode': 200, 'body': base.dump_json(dict(succ=True, message='COMMID ID is not found, skip the processing.')) }
	
		mode = parse_process_mode(params)
		if mode not in [ 'all', 'single' ]:
			message = 'Event {} of branch {} does not need to be handled.'.format(params.get('event_type'), params.get('target_branch'))
			print(message)
			return { 'statusCode': 200, 'body': base.dump_json(dict(succ=True, message=message)) }
		params['mode'] = mode
		
		# 获取Code Lib Context
		repo_context = codelib.init_repo_context(params)

		# 解析.codereview规则
		desc = codelib.get_repository_file(repo_context, '.codereview.yaml', params['commit_id'])
		variables = yaml.safe_load(desc) if desc else dict()
		params['target'] = parse_target(variables)
		if 'target' in variables: variables.pop('target')
		if 'targets' in variables: variables.pop('targets')
		params['variables'] = variables
		print('Parsed variables:', base.dump_json(variables))
		
		# 向数据库插入记录
		dynamodb.Table(REQUEST_TABLE).put_item(Item={
			'commit_id': params['commit_id'],
			'request_id': params['request_id'],
			'mode': params['mode'],
			'status': 'Start',
			'task_complete': 0,
			'task_failure': 0,
			'task_total': 0,
			'create_time': str(current_time),
			'update_time': str(current_time),
		})
		print('Complete inserting record to ddb.')
		
		# 调用第二个Lambda函数，使用'Event'进行异步调用
		payload = base.dump_json(params)
		lambda_client.invoke(
			FunctionName=TASK_DISPATCHER_FUN_NAME,
			InvocationType='Event',
			Payload=payload,
		)
		print('Complete invoking task dispatcher, payload is', payload)

		return { 'statusCode': 200, 'body': base.dump_json(dict(succ=True)) }

	except Exception as ex:
		print('Fail to process webhook request: {}, location: {}'.format(ex, traceback.format_exc()))
		return { 'statusCode': 200, 'body': base.dump_json(dict(succ=False, message=str(ex))) }
