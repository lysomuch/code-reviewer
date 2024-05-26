import re, os, json, datetime, traceback
import base
import boto3

get_s3_object = lambda s3, bucket, key: s3.Object(bucket, key).get()['Body'].read().decode('utf-8')
put_s3_object = lambda s3, bucket, key, text, content_type: s3.Object(bucket, key).put(Body=text, ContentType=content_type)

def get_json_directory(project_name, mode, commit_id):
	name = re.sub(r'[^a-zA-Z0-9]+', '_', project_name.lower())
	name = re.sub(r'^_+|_+$', '', name)
	return '{}/{}/{}'.format(name, commit_id, mode)
	
def generate_report_content(mode, project_name, data):

	# 读取Report Template
	path = os.path.dirname(os.path.abspath(__file__))
	json_file = os.path.join(path, 'report_template.html')
	with open(json_file, 'r') as f:
		content = f.read()

	# 准备变量
	datetime_str = datetime.datetime.now().strftime("%Y年%m月%d日 %H时%M分%S秒")
	if mode == 'all':
		title = f'{project_name}代码审核报告(整库审核版)'
	elif mode == 'single':
		title = f'{project_name}代码审核报告(单文件审核版)'
	else:
		title = f'{project_name}代码审核报告'
		print(f'Mode({mode}) is invalid.')
	subtitle = f'检测时间: {datetime_str}'

	# 替换数据
	all_data_text = repr(base.dump_json(data, indent=4))[1:-1]
	replacement = f"""<script id="diy">
	const expand_all = false;
	const title = '{title}';
	const subtitle = '{subtitle}';
	const data = {all_data_text};
	</script>
	"""
	print('Replacement:', dict(placement=replacement))
	content = re.sub(r'<script id="diy">.*?</script>', replacement, content, flags=re.DOTALL)
	print('New Content:', dict(content=content))

	return title, subtitle, content

def generate_report(record, event, context, clients):

	commit_id = event.get('commit_id')
	request_id = event.get('request_id')
	mode = event.get('mode')

	label = f'request record(commit_id={commit_id}, request_id={request_id})'
	print(f'Generating report for {label}.')

	project_name = context.get('project_name')
	directory = get_json_directory(project_name, request_id, commit_id)
	
	# 写入data.js文件
	dynamodb = clients.get('dynamodb')
	TASK_TABLE = os.getenv('TASK_TABLE')
	items = dynamodb.Table(TASK_TABLE).query(
		KeyConditionExpression='request_id=:rid',
		ExpressionAttributeValues={ ':rid': request_id }
	)
	ret = [ item for item in items.get('Items') ]
	all_data = []
	for item in items.get('Items'):
		try:
			if item.get('succ') == True:
				print('Found successful result for task(request_id={request_id}, number={number}): {result}'.format(**item))
				json_data = json.loads(item.get('result'))
				print('Parsed JSON data: ', json_data)
				if type(json_data) is list:
					all_data = all_data + json_data
				else:
					all_data.append(json_data)
			else:
				print('Found failed result for task(request_id={request_id}, number={number}).')
		except Exception as ex:
			print('Tail to get result for task:', ex)
			traceback.print_exc()
	print('Got all data: ', all_data)

	# 写入HTML文件
	title, subtitle, content = generate_report_content(mode, project_name, all_data)
	s3 = clients.get('s3')
	BUCKET_NAME = os.getenv('BUCKET_NAME')
	key = f'{directory}/index.html'
	put_s3_object(s3, BUCKET_NAME, key, content, 'Content-Type: text/html')
	print(f'Report is created to s3://{BUCKET_NAME}/{key}')
	
	# 为index.html产生Presign URL
	presigned_url = s3.Object(BUCKET_NAME, key).meta.client.generate_presigned_url('get_object', Params={'Bucket': BUCKET_NAME, 'Key': key}, ExpiresIn=3600 * 24 * 30)
	print(f'Report URL:', presigned_url)

	return dict(title=title, subtitle=subtitle, url=presigned_url, data=all_data)
