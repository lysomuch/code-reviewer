import os, re, json
import gitlab
import base

DEFAULT_MODE 			= os.getenv('DEFAULT_MODE', 'all')
DEFAULT_MODEL 			= os.getenv('DEFAULT_MODEL', 'claude3')

def get_diff_files(project, from_commit_id, previous_commit_id):
	commits = project.commits.list(ref_name=f'{from_commit_id}..{previous_commit_id}')
	files = []
	for commit in reversed(commits):
		diff = commit.diff()
		for item in diff:
			if item['new_file']:
				files.append(item['new_path'])
			elif item['renamed_file']:
				files.remove(item['old_path'])
				files.append(item['new_path'])
			elif item['deleted_file']:
				files.remove(item['new_path'])
			else:
				files.append(item['new_path'])
	return files

def parse_gitlab_parameters(event):
	
	body = json.loads(event.get('body', '{}'))
	event_type = body.get('object_kind', '').lower()
	print(f'Received Gitlab event[{event_type}]:', base.dump_json(body))

	headers = event.get('headers', {})
	
	body_project = body.get('project', {})
	web_url = body_project.get('web_url')
	path_with_namespace = body_project.get('path_with_namespace')
	repo_url = web_url[:-len(path_with_namespace)]

	# 计算Target branch
	target_branch = None
	if event_type == 'push':
		target_branch = body.get('ref')
		if target_branch.startswith('refs/heads/'):
			target_branch = target_branch[11:]
		else:
			print('Can\'t determine target branch for the field "ref" does not meet the expected format:', body)
	elif event_type == 'merge_request':
		target_branch = body.get('object_attributes', {}).get('target_branch')
	
	params=dict(
		source = 'gitlab',
		web_url = web_url,
		project_id = body_project.get('id'),
		project_name = body_project.get('name'),
		repo_url = repo_url,
		private_token = headers.get('X-Gitlab-Token'),
		target_branch = target_branch,
		event_type = event_type
	)
	if not params.get('project_id'):
		params['project_id'] = body_project.get('path_with_namespace')

	if event_type == 'push':
		params['commit_id'] = body.get('after')
		params['previous_commit_id'] = body.get('before')
		params['ref'] = body.get('ref')
		params['username'] = body.get('user_username'),
	elif event_type == 'merge_request':
		merge_status = body.get('object_attributes', {}).get('merge_status')
		if merge_status in  ['checking']:
			params['commit_id'] = body.get('object_attributes', {}).get('last_commit', {}).get('id')
			params['ref'] = body.get('object_attributes', {}).get('source_branch')
			params['username'] = body.get('user', {}).get('username')
			print(f'The merge status is {merge_status}, it is going to invoke code review.')	
		else:
			params['commit_id'] = None
			params['ref'] = None
			params['username'] = None
			print(f'The merge status is {merge_status}, it will skip code review.')	

	if params.get('commit_id') is None: 
		params['commit_id'] = ''

	return params
	
def get_gitlab_file(project, path, ref):
	try:
		print(f'Try to get gitlab file in ref({ref}): {path}')
		content = project.files.raw(file_path=path, ref=ref)
		print(f'Got gitlab file {path} @ {ref}: {content}')
		return content.decode()
	except Exception as ex:
		print(f'Fail to get git file {path} @ {ref}: {ex}')
		return None

def get_gitlab_file_content(project, file_path, ref_name):
	file_content = project.files.raw(file_path=file_path, ref=ref_name).decode()
	print(f'File content({file_path}):', dict(path=file_path, content=file_content))
	return file_content


def init_gitlab_context(repo_url, project_id, private_token):
	try:
		gl = gitlab.Gitlab(repo_url if repo_url else None, private_token=private_token)
		print(f'Try to get project({project_id})')
		project = gl.projects.get(project_id)
		return project
	except Exception as ex:
		raise Exception(f'Fail to get Gitlab project: {ex}') from ex
	

def get_project_code_text(repo_context, commit_id, targets):
	
	project = repo_context
	
	# 用于存储文件路径的数组
	items = project.repository_tree(ref=commit_id, all=True, recursive=True)
	file_paths = base.filter_targets([ item['path'] for item in items if item['type'] == 'blob'], targets)
	print('Scaned {} files after ext filtering in repository for commit_id({}), filters({}).'.format(len(file_paths), commit_id, targets))

	text = ''
	for file_path in file_paths:
		try:
			file_content = get_gitlab_file_content(project, file_path, commit_id)
			section = f'{file_path}\n```\n{file_content}\n```'
			text = '{}\n\n{}'.format(text, section) if text else section			
		except Exception as ex:
			print(f'Fail to get file({file_path}) content: {ex}')
  
	return text