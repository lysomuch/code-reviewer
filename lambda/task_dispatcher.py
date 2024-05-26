import boto3
import os, re, base64, datetime, traceback
import base, codelib



# Environment variables and constants
REQUEST_TABLE 			= os.getenv('REQUEST_TABLE')
RULE_TABLE 				= os.getenv('RULE_TABLE')
TASK_SQS_URL 			= os.getenv('TASK_SQS_URL')

# Initialize AWS services clients
dynamodb = boto3.resource("dynamodb")
sqs_client = boto3.client("sqs")

def encode_base64(string):
	string_bytes = string.encode('utf-8')
	base64_bytes = base64.b64encode(string_bytes)
	base64_string = base64_bytes.decode('ascii')
	return base64_string

def decode_base64(base64_string):
	base64_bytes = base64_string.encode('ascii')
	string_bytes = base64.b64decode(base64_bytes)
	string = string_bytes.decode('utf-8')
	return string

def get_rules(mode):
	items = dynamodb.Table(RULE_TABLE).query(
		KeyConditionExpression='#mode=:mode',
		ExpressionAttributeNames={ '#mode': 'mode' },
		ExpressionAttributeValues={ ':mode': mode }
	)
	ret = [ item for item in items.get('Items') ]
	return ret

def match_glob_pattern(string, pattern):
	regex = re.escape(pattern)
	regex = regex.replace(r'\*\*', '.*')
	regex = regex.replace(r'\*', '[^/]*')
	regex = regex.replace(r'\?', '.')
	match = re.match(regex, string)
	return bool(match)

def send_message(data):
	sqs_url = TASK_SQS_URL
	try:
		print(f'Prepare to send message to SQS({sqs_url}): {data}')
		message = encode_base64(base.dump_json(data))
		response = sqs_client.send_message(QueueUrl=sqs_url, MessageBody=message)
		print(f'Succeed to send message to SQS({sqs_url}) in base64: {message}')
		return True
	except Exception as ex:
		print(f'Fail to send message to SQS({sqs_url}): {ex}')
		traceback.print_exc()
		return False

def format_prompt(pattern, variables, commit_id=None, code=None):
	text = pattern
	for key in variables:
		text = text.replace('{{' + key + '}}', variables.get(key, '').strip())
	if commit_id: 
		text = text.replace('{{commit_id}}', commit_id)
	if code: 
		text = text.replace('{{code}}', code)
	return text

def get_prompt_data(mode, rule, commit_id, code, variables):
	
	if rule.get('mode') != mode: return None
	
	if rule.get('model') == 'claude3':
		prompt_system = format_prompt(rule.get('prompt_system'), variables, code=code)
		prompt_user = format_prompt(rule.get('prompt_user'), variables, code=code)
		return dict(prompt_system=prompt_system, prompt_user=prompt_user)
	else:
		return None
	
def send_task_to_sqs(event, request_id, commit_id, mode, contents, variables):
	
	rules = get_rules(mode)
	print('Get rules:', base.dump_json(rules))
	
	# 更新记录的任务总数
	count = len(contents) * len(rules)
	try:
		table = dynamodb.Table(REQUEST_TABLE)
		table.update_item(
			Key = dict(commit_id=commit_id, request_id=request_id),
			UpdateExpression = "set #s = :s, update_time = :t, task_complete = :tc, task_failure = :tf, task_total = :tt",
			ExpressionAttributeNames = { '#s': 'status' },
			ExpressionAttributeValues = {
				':s': 'Initializing',
				':t': str(datetime.datetime.now()),
				':tc': 0,
				':tf': 0,
				':tt': count,
			},
			ReturnValues = "ALL_NEW",
		)
	except Exception as ex:
		print(f'Fail to update status for request record(commit_id={commit_id}), request_id={request_id}): {ex}')
		traceback.print_exc()
		return False
		
	# 每一个content与每一个rule组合成一个Bedrock Task
	number = 0
	for content in contents:
		for rule in rules:
			result = True
			try:
				model = rule.get('model')
				prompt_data = get_prompt_data(mode, rule, commit_id, content.get('content'), variables)
				print('Make up new prompt data:' , base.dump_json(prompt_data))
				if not prompt_data: continue
			
				number += 1
				rule_name = rule.get('name', 'none')
				identity = '{}-{}-{}-{}-{}'.format(mode, model, number, rule_name, content.get('path', 'none')).lower()
				item = dict(
					context = event, 
					commit_id = commit_id, 
					request_id = request_id,
					number = number,
					mode = mode, 
					model = model,
					filepath = content.get('filepath'),
					rule_name = rule_name,
					prompt_data=prompt_data
				)
				result = send_message(item)
				if not result:
					print('Fail to send bedrock task to SQS')
			except Exception as ex:
				print(f'Fail to create SQS task: {ex}')
				result = False
			
			if not result:
				try:
					table.update_item(
						Key=dict(commit_id=commit_id, scan_scope=mode),
						UpdateExpression="set task_failure = task_failure + :tf",
						ExpressionAttributeValues={ ':tf': 1 },
						ReturnValues="ALL_NEW",
					)
				except Exception as ex:
					print(f'Fail to update FAILURE COUNT for commit_id({commit_id}) and mode({mode}): {ex}')

	# 最后一个Task，定期检查任务进度
	result = send_message(dict(
		type = 'checker',
		context = event, 
		request_id = request_id,
		commit_id = commit_id, 
		mode = mode, 
	))
 
	return True

def update_dynamodb_status(commit_id, scan_scope, status, file_num):
	
	key = { 'commit_id': commit_id, 'scan_scope': scan_scope }
	
	# 检查数据存在性
	table = dynamodb.Table(REQUEST_TABLE)
	item = table.get_item(Key=key)
	if item.get('Item') is None:
		raise Exception(f'Cannot find record for COMMIT ID({commit_id}) and SCAN SCOPE({scan_scope}).')
	
	# 更新数据
	table.update_item(
		Key=key,
		UpdateExpression="set task_status = :s, update_at = :t, file_num = file_num + :m",
		ExpressionAttributeValues={
			":s": status,
			":t": str(datetime.datetime.now()),
			":m": file_num,
		},
		ReturnValues="ALL_NEW",
	)


def validate_sqs_event(event):
	"""
	mode = all
	mode = single，commit_id, previous_commit_id
	"""
	required = [ 'commit_id', 'request_id', 'mode', 'target' ]
	if event['mode'] == 'single':
		required.append('previous_commit_id')
		
	for field in required:
		if field not in event:
			raise Exception(f'SQS event does not have field {field} - {event}')
	return True

def lambda_handler(event, context):
	
	print('Event:', base.dump_json(event))
	
	# 校验SQS Event必要字段
	try:
		validate_sqs_event(event)
	except Exception as ex:
		print('Fail to validate SQS event:', ex)
		return {"statusCode": 500, "body": str(ex)}
	
	# 初始化变量
	mode            = event['mode']
	commit_id       = event['commit_id']
	request_id 		= event['request_id']
	previous_commit_id 	= event.get('previous_commit_id')
	
	targets = [ target.strip() for target in event['target'].split(',') if target.strip() ]
	if not targets:
		print('Skipped code review: target is empty.')
		return
	
	# 获取Code Lib Context
	repo_context = codelib.init_repo_context(event)
		
	# 计算需要处理的文件，存入contents中
	contents = []
	
	if mode == 'all':
		text = codelib.get_project_code_text(repo_context, commit_id, targets)      # 计算完整的代码块
		contents.append(dict(path = '<The Whole Project>', content=text))
		
	if mode == 'single':

		# 获取涉及的文件
		files = codelib.get_involved_files(repo_context, commit_id, previous_commit_id)
		print('Get involved files before filtering: ', base.dump_json(files))
		files = base.filter_targets(files, targets)
		print('Filter files by {}: {}'.format(targets, base.dump_json(files)))

		# 逐个文件组装成提示词片段
		for filepath in files:
			code = codelib.get_repository_file(repo_context, filepath, commit_id)
			content = f'{filepath}\n```\n{code}\n```'
			contents.append(dict(path = filepath, content = content))
		print('Prompt segments for involved files:', base.dump_json(contents))
			
	result = send_task_to_sqs(event, request_id, commit_id, mode, contents, event.get('variables'))
	return {"statusCode": 200, "body": dict(succ = result) }
