import datetime
import gitlab_code

def init_repo_context(params):
	"""
	{ repo_url, project_id, private_token }
	"""
	source = 'gitlab' # Change to parse from params.
	if source == 'gitlab':
		project = gitlab_code.init_gitlab_context(params.get('repo_url'), params.get('project_id'), params.get('private_token'))
		return dict(source='gitlab', project=project)
	else:
		raise Exception(f'Code lib source({source}) is not support yet.')

def parse_parameters(event):
	source = 'gitlab'
	if source == 'gitlab':
		params = gitlab_code.parse_gitlab_parameters(event)
		date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
		params['request_id'] = '{}_{}_{}'.format(date_str, params['source'], params['username'])
		return params
	else:
		raise Exception(f'Code lib source({source}) is not support yet.')

def get_project_code_text(repo_context, commit_id, targets):
	source = repo_context.get('source')
	if source == 'gitlab':
		return gitlab_code.get_project_code_text(repo_context.get('project'), commit_id, targets)
	else:
		raise Exception(f'Code lib source({source}) is not support yet.')

def get_involved_files(repo_context, commit_id, previous_commit_id):
	source = repo_context.get('source')
	if source == 'gitlab':
		files = gitlab_code.get_diff_files(repo_context.get('project'), previous_commit_id, commit_id)
		return files
	else:
		raise Exception(f'Code lib source({source}) is not support yet.')

def get_repository_file(repo_context, filepath, commit_id):
	source = repo_context.get('source')
	if source == 'gitlab':
		return gitlab_code.get_gitlab_file(repo_context.get('project'), filepath, commit_id)
	else:
		raise Exception(f'Code lib source({source}) is not support yet.')
	