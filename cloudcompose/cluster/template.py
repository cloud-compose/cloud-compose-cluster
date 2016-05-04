import jinja2
from os.path import join

class Template:
    def __init__(self, search_path):
        if not isinstance(search_path, list):
            search_path = [search_path]
        self.env = jinja2.Environment(loader=jinja2.FileSystemLoader(search_path))

    def render(self, template_file, template_data):
        template_obj = self.env.get_template(template_file)
        return template_obj.render(template_data)

