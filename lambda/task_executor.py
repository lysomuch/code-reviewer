import boto3
import traceback
import os, json, time, datetime, base64
import base, report

TASK_TABLE 				= os.getenv('TASK_TABLE')
REQUEST_TABLE 			= os.getenv('REQUEST_TABLE')
TASK_SQS_URL 			= os.getenv('TASK_SQS_URL')
SNS_TOPIC_ARN 			= os.getenv('SNS_TOPIC_ARN')
SQS_MAX_DELAY 			= base.str_to_int(os.getenv('SQS_MAX_DELAY', '60'))   		# 最大延迟时间(秒)
SQS_BASE_DELAY 			= base.str_to_int(os.getenv('SQS_BASE_DELAY', '2'))   		# 初始延迟时间(秒)
SQS_MAX_RETRIES 		= base.str_to_int(os.getenv('SQS_MAX_RETRIES', '5'))		# 最大重试次数
MAX_FAILED_TIMES 		= base.str_to_int(os.getenv('MAX_FAILED_TIMES', '6'))
MAX_TOKEN_TO_SAMPLE 	= base.str_to_int(os.getenv('MAX_TOKEN_TO_SAMPLE', '10000'))
REPORT_TIMEOUT_SECONDS 	= base.str_to_int(os.getenv('REPORT_TIMEOUT_SECONDS', '900'))
TOP_P 					= base.str_to_float(os.getenv('TOP_P', '0.9'))
TEMPERATURE 			= base.str_to_float(os.getenv('TEMPERATURE', '0.1'))

bedrock = boto3.client(service_name="bedrock-runtime")
dynamodb = boto3.resource("dynamodb")
s3 = boto3.resource("s3")
sqs = boto3.client("sqs")
sns = boto3.resource('sns')

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



def handle_progress_check(record, event, context):

	print('Progress Event:', base.dump_json(event))
	print('Progress Context:', base.dump_json(context))

	commit_id = event.get('commit_id')
	request_id = event.get('request_id')
	
	print(f'Checking code review result for request record(commit_id={commit_id}, request_id={request_id})...')

	is_completed = False
	
	# 找不到数据视为已经完成
	print('Table:',REQUEST_TABLE)
	item = dynamodb.Table(REQUEST_TABLE).get_item(Key=dict(commit_id=commit_id, request_id=request_id), ConsistentRead=True)

	label = f'request record(commit_id={commit_id}, request_id={request_id})'
	if item.get('Item') is None:
		is_completed = True
		print(f'Mark code review complete. For cannot find record for {label}.')
	else:
		item = item.get('Item')
		print('Load request record:', item)
		total, completes, failures = [ item.get(key) for key in ['task_total', 'task_complete', 'task_failure' ] ]
		# 检查整个Code Review是否完成
		if completes + failures >= total:
			is_completed = True
			print(f'Mark code review complete. For all sub-task are complete for {label}.')
		else:
			print(f'Code review is uncomplete. Completes({completes}) + Failures({failures}) < Total({total}) for {label}.')

			# 检查整个Code Review是否超时
			create_time = item.get('create_time')
			specified_time = datetime.datetime.strptime(create_time, "%Y-%m-%d %H:%M:%S.%f")
			current_time = datetime.datetime.now()
			time_diff_seconds = (current_time - specified_time).total_seconds()
			if time_diff_seconds > REPORT_TIMEOUT_SECONDS:
				is_completed = True
				print(f'Mark code review complete. For timeout({REPORT_TIMEOUT_SECONDS} seconds) for {label}.')				

	# Code Review完成，则产生报告
	if is_completed:

		result = report.generate_report(record, event, context, dict(s3=s3, dynamodb=dynamodb))
		
		# 更新数据库Task状态
		dynamodb.Table(REQUEST_TABLE).update_item(
			Key = {'commit_id': commit_id, 'request_id': request_id},
			UpdateExpression = 'set task_status = :s, update_time = :t',
			ExpressionAttributeValues = { ':s': 'Complete', ':t': str(datetime.datetime.now()) },
			ReturnValues = 'ALL_NEW'
		)

		# 发送SNS消息
		message = dict(title=result.get('title'), subtitle=result.get('subtitle'), report_url=result.get('url'), data=result.get('data'))
		response = sns.Topic(SNS_TOPIC_ARN).publish(Message=base.dump_json(message), Subject=result.get('title', 'none'))
		print('SNS message is sent:', response['MessageId'])

	# Code Review未完成，则继续放一个Checker到SQS
	if not is_completed:	
		try:
			# message_data = dict(type = 'checker', context = context, commit_id = commit_id, request_id = request_id, mode=mode )
			message = base.encode_base64(base.dump_json(event))
			sqs.send_message(QueueUrl=TASK_SQS_URL, MessageBody=message, DelaySeconds=10 )
			print(f'Code review is not complete, resend checker back to SQS:', event)
		except Exception as ex:
			raise Exception('Fail to create checker repeatly.') from ex

	# 删除原Checker
	try:
		sqs.delete_message(QueueUrl=TASK_SQS_URL, ReceiptHandle=record["receiptHandle"])
	except Exception as ex:
		print('Fail to delete the old checker:' , ex)

def invoke_claude3(model, prompt_data, task_name):

	params = dict(
		max_tokens = MAX_TOKEN_TO_SAMPLE,
		temperature = TEMPERATURE,
		top_p = TOP_P,
		anthropic_version= 'bedrock-2023-05-31',
	)
	
	if prompt_data.get('prompt_system'):
		params['system'] = prompt_data.get('prompt_system')
	
	params['messages'] = [
		{
			'role': 'user',
			'content': [
				{
					'type': 'text',
					'text': prompt_data.get('prompt_user', '')
				}
			]
		}
	]
	
	if model == 'claude3-opus':
		llm_id = 'anthropic.claude-3-opus-20240229-v1:0'
	elif model == 'claude3-sonnet':
		llm_id = 'anthropic.claude-3-sonnet-20240229-v1:0'
	elif model == 'claude3-haiku':
		llm_id = 'anthropic.claude-3-haiku-20240307-v1:0'
	elif model == 'claude3': # 默认使用Sonnet
		llm_id = 'anthropic.claude-3-sonnet-20240229-v1:0'
	else:
		raise Exception(f'Invalid claude3 model {model}')
		
	try:
		print(f'Bedrock - Invoking claude3 for {task_name}:', base.dump_json(params))
		response = bedrock.invoke_model(body=base.dump_json(params), modelId=llm_id)
		response_body = json.loads(response.get('body').read())
		reply = response_body.get('content')[0]
		print(f'Bedrock - Claude3 replied for {task_name}:', base.dump_json(reply))
		return reply['text']
	except Exception as ex:
		raise Exception(f'Fail to invoke Claude3: {ex}') from ex

def invoke_bedrock(model, full_prompt, task_name):
	# 这里可以设置策略来选择LLM，此处暂时仅仅选择Claude3
	if model in ['claude3', 'claude3-haiku', 'claude3-sonnet', 'claude3-opus']:
		reply = invoke_claude3(model, full_prompt, task_name)
	return reply

def validate_sqs_event(event):
	required = [ 'context', 'commit_id', 'mode', 'model', 'rule_name', 'prompt_data' ]
	for field in required:
		if field not in event:
			raise Exception(f'SQS event does not have field {field} - {event}')
	return True

def handle_code_review(record, event, context):

	print('Task Event:', base.dump_json(event))
	print('Task Context:', base.dump_json(context))

	request_id = event.get('request_id')
	number = event.get('number')
	label = f'task(request_id={request_id}, number={number})'
	print(f'Try to do code review for {label}...')

	# 校验SQS Event必要字段
	validate_sqs_event(event)
	mode 				= event['mode']
	model 				= event['model'].lower()
	commit_id 			= event['commit_id']
	prompt_data 		= event['prompt_data']
	current_timestamp 	= datetime.datetime.now()

	error_messages = []
	retries, delay = 0, SQS_BASE_DELAY
	while retries < SQS_MAX_RETRIES:
		try:
			if retries > 0:
				print(f'Retry for the {retries} times...')
				
			# 调用LLM
			reply = invoke_bedrock(model, prompt_data, label)
			result = dict(
				commit_id = commit_id,
				request_id = request_id,
				rule = event['rule_name'],
				content = eval(reply),
				timestamp = str(current_timestamp),
			)

			update_complete_task(commit_id, request_id, number, mode, result)
			print(f'Review result is saved in {label}: {result}')
			return 
   
		except Exception as ex:
			retries += 1
			delay = min(delay * 2, SQS_MAX_DELAY)  # 计算下一次重试的延迟时间
			print(f'Fail to process SQS record for the {retries} times: {ex}')
			traceback.print_exc()
			error_messages.append(dict(err=ex, traceback=traceback.format_exc()))
			print(f"Retrying in {delay} seconds...")
			time.sleep(delay)  # 延迟一段时间后重试
	
	update_failure_task(commit_id, request_id, number, mode, base.dump_json(error_messages))
	# 跳出循环即表示重试多次失败
	print(f'Review failure is saved in {label}.')
	raise Exception(f'Fail to process {label} for {SQS_MAX_RETRIES} times')

def update_complete_task(commit_id, request_id, number, mode, result):
	try:
		datetime_str = str(datetime.datetime.now())
		# 更新Task表
		dynamodb.Table(TASK_TABLE).put_item(Item={
			'request_id': request_id,
			'number': number,
			'mode': mode,
			'succ': True,
			'result': base.dump_json(result),
			'create_time': datetime_str,
			'update_time': datetime_str,
		})
		# 更新Request表
		dynamodb.Table(REQUEST_TABLE).update_item(
			Key = { 'commit_id': commit_id, 'request_id': request_id },
			UpdateExpression = 'set task_status = :s, task_complete = task_complete + :tc, update_time = :t',
			ExpressionAttributeValues = { ':s': 'LLM_PROCESSING', ':tc': 1, ':t': datetime_str },
			ReturnValues = 'ALL_NEW'
		)
	except Exception as e:
		raise Exception (f'Fail to update TASK COMPLETE for commit_id({commit_id}) and mode({mode}).') from e
	
def update_failure_task(commit_id, request_id, number, mode, error_message):
	try:
		datetime_str = str(datetime.datetime.now())
		# 更新Task表
		dynamodb.Table(TASK_TABLE).put_item(Item={
			'request_id': request_id,
			'number': number,
			'mode': mode,
			'succ': False,
			'message': error_message,
			'create_time': datetime_str,
			'update_time': datetime_str,
		})
		# 更新Request表
		dynamodb.Table(REQUEST_TABLE).update_item(
			Key = {'commit_id': commit_id, 'scan_scope': mode},
			UpdateExpression = 'set task_status = :s, task_failure = task_failure + :tf, update_time = :t',
			ExpressionAttributeValues = { ':s': 'LLM_PROCESSING', ':tf': 1, ':t': datetime_str },
			ReturnValues = 'ALL_NEW'
		)
	except Exception as ex:
		print(f'Fail to update TASK FAILURE for commit_id({commit_id}) and mode({mode}).')
	
def lambda_handler(event, context):

	print('Event:', base.dump_json(event))
	print('Receiving {} SQS records'.format(len(event["Records"])))

	clients = dict(dynamodb=dynamodb, sqs=sqs, sns=sns)
	
	batch_item_failures, batch_item_successes = [], []
	for record in event["Records"]:
		
		print('Processing SQS record:', record)

		base64_text = record["body"]
		body_text = decode_base64(base64_text)
		print('Plain body:', body_text)
		
		sqs_event = json.loads(body_text)
		sqs_context = sqs_event.get('context', {})

		# commit_id = sqs_event.get('commit_id')
		# mode = sqs_event.get('mode')

		if sqs_event.get('type') == 'checker':
			try:
				handle_progress_check(record, sqs_event, sqs_context)
				batch_item_successes.append({"itemIdentifier": record['messageId']})
			except Exception as ex:
				print('Fail to check code review result: {}: {}'.format(ex, traceback.format_exc()))
				batch_item_failures.append({"itemIdentifier": record['messageId']})
		else:
			try:
				result = handle_code_review(record, sqs_event, sqs_context)
				batch_item_successes.append({"itemIdentifier": record['messageId']})
			except Exception as ex:
				print('Fail to check code review result: {}: {}'.format(ex, traceback.format_exc()))
				batch_item_failures.append({"itemIdentifier": record['messageId']})

	batch_response = dict(batchItemSeccesses = batch_item_successes, batchItemFailures = batch_item_failures)
	print('SQS process results:', batch_response)
	return batch_response
