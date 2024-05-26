import os, re, json
import base
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


import os
import re

def generate_report(title, subtitle, data):
    path = os.path.dirname(os.path.abspath(__file__))
    json_file = os.path.join(path, 'report_template.html')
    with open(json_file, 'r', encoding='utf-8') as f:
        template = f.read()

    # 替换标题和副标题
    template = re.sub(r'<title id="page-title"></title>', f'<title>{title}</title>', template)
    template = re.sub(r'<h1 id="main-title"></h1>', f'<h1>{title}</h1>', template)
    template = re.sub(r'<h3 id="detection-date"></h3>', f'<h3>{subtitle}</h3>', template)

    # 替换数据
    data_html = ''
    level_containers = {}
    for item in sorted(sum([rule['content'] for rule in data], []), key=lambda x: ['trivial', 'major', 'serious'].index(x.get('level', 'major'))):
        level = item.get('level', 'major')
        if level not in ['serious', 'major', 'trivial']:
            continue

        level_chinese = {
            'serious': '严重问题',
            'major': '主要问题',
            'trivial': '琐碎问题'
        }[level]

        if level not in level_containers:
            level_container_html = f'<div class="level-container"><h2>{level_chinese}</h2><ul class="issue-list"></ul></div>'
            level_containers[level] = level_container_html

        title = item['title']
        filepath = item['filepath']
        content = item['content']

        # 对 content 字段进行换行处理
        content_html = '<br>'.join(content.split('\n'))

        # 处理代码片段
        content_html = re.sub(r'```(\w+)?([\s\S]*?)```', lambda m: f'<pre class="code-block language-{m.group(1) or ""}"><code>{m.group(2)}</code></pre>', content_html)

        issue_html = f'''
            <li class="issue-item">
                <div class="issue-header">
                    <span class="issue-header-text">{title} ({filepath})</span>
                    <span class="issue-toggle-icon">-</span>
                </div>
                <div class="issue-content">
                    <div class="metadata-container">
                        <p><strong>Title:</strong> {title}</p>
                        <p><strong>Level:</strong> {level_chinese}</p>
                        <p><strong>File Path:</strong> {filepath}</p>
                    </div>
                    <div class="content-container">{content_html}</div>
                </div>
            </li>
        '''
        level_containers[level] = level_containers[level].replace('</ul></div>', issue_html + '</ul></div>')

    for level_container_html in ['serious', 'major', 'trivial']:
        if level_container_html in level_containers:
            data_html += level_containers[level_container_html]

    template = re.sub(r'<div id="report-container"></div>', f'<div id="report-container">{data_html}</div>', template)

    # 移除 JavaScript 代码
    template = re.sub(r'<script id="diy">[\s\S]*?</script>', '', template)

    return template

def send_mail(message):

	message_data = json.loads(message)
	title = message_data.get('title') 
	subtitle = message_data.get('subtitle') 
	data = message_data.get('data')
	report_url = message_data.get('report_url')
	
	smtp_server = os.getenv('SMTP_SERVER')
	smtp_port = os.getenv('SMTP_PORT')
	smtp_username = os.getenv('SMTP_USERNAME')
	smtp_password = os.getenv('SMTP_PASSWORD')
	report_sender = os.getenv('REPORT_SENDER')
	report_receiver = os.getenv('REPORT_RECEIVER')

	html = generate_report(title, subtitle, data)
	replacement = f'<body><div style="border: 1px dashed gray; padding: 5px;">报告原始地址：<a href="{report_url}" target="_blank">点击打开</a></div>'
	html = re.sub(r'<body>', replacement, html)
	  
	msg = MIMEMultipart('alternative')
	msg.attach(MIMEText(html, 'html', 'utf-8'))
	msg['Subject'] = title if title else 'No Title'
	msg['From'] = report_sender
	msg['To'] = report_receiver

	with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
		server.login(smtp_username, smtp_password)
		server.send_message(msg)
		print(f'Report is sent to mail {report_receiver}:', msg['Subject'])

def lambda_handler(event, context):
	
	print('Event:', base.dump_json(event))

	for record in event.get('Records'):
		sns_message = record.get('Sns')
		if sns_message:
			subject = sns_message.get('Subject')
			print(f'Got SNS subject: {subject}')
			message = sns_message.get('Message')
			print(f'Got SNS message: {message}')
			
			# 发送邮件
			send_mail(message)

			# 触发飞书/微信/钉钉的WebHook
			# TODO Write your code here

			# 其他操作
			# TODO Write your code here

