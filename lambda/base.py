import re, json, base64, decimal, datetime

str_to_float = lambda string: float(string)
str_to_int = lambda string: int(string)
is_target_file = lambda filepath, patterns: any(match_glob_pattern(filepath, pattern) for pattern in patterns)
filter_targets = lambda filepaths, targets: [path for path in filepaths if is_target_file(path, targets)]

def trace(message):
	print('Trace>', message)

class CustomJsonEncoder(json.JSONEncoder):
	def default(self, obj):
		if isinstance(obj, datetime.datetime):
			return obj.strftime("%Y-%m-%d %H:%M:%S")
		if isinstance(obj, bytes):
			return str(obj, encoding='utf-8')
		if isinstance(obj, int):
			return int(obj)
		elif isinstance(obj, float):
			return float(obj)
		elif isinstance(obj, decimal.Decimal):
			return float(obj)
		# elif isinstance(obj, array):
		#    return obj.tolist()
		else:
			return super(CustomJsonEncoder, self).default(obj)
		
def dump_json(data, indent=None):
	if indent is not None:
		return json.dumps(data, cls=CustomJsonEncoder, ensure_ascii=False, indent=indent)
	else:
		return json.dumps(data, cls=CustomJsonEncoder, ensure_ascii=False)

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

def match_glob_pattern(string, pattern):
	regex = re.escape(pattern)
	regex = regex.replace(r'\*\*', '.*')
	regex = regex.replace(r'\*', '[^/]*')
	regex = regex.replace(r'\?', '.')
	match = re.match(regex, string)
	return bool(match)
