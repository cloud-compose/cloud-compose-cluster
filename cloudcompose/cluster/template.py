import jinja2
from os.path import join
from os import environ

class Template:
    def __init__(self, search_path):
        if not isinstance(search_path, list):
            search_path = [search_path]
        self.env = jinja2.Environment(loader=jinja2.FileSystemLoader(search_path), undefined=jinja2.StrictUndefined)

    def render(self, template_file, template_data):
        self._add_environment(template_data)
        template_obj = self.env.get_template(template_file)
        return template_obj.render(template_data)

    def _add_environment(self, template_data):
        for key in environ.keys():
            if key not in template_data:
                template_data[key] = environ[key]

