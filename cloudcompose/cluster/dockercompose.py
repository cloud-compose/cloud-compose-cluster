from cloudcompose.cluster.template import Template
from os.path import join, isfile, isdir, split

class DockerCompose:
    def __init__(self, search_path=['cloud-compose', '.']):
        self.search_path = search_path
        self.docker_compose_files = ['docker-compose.yml', 'docker-compose.yaml']
        self.docker_compose_override_files = ['docker-compose.override.yml', 'docker-compose.override.yaml']

    def yaml_files(self, config_data):
        docker_compose = self._read_docker_compose()
        docker_compose_override = self._render_docker_compose_override(config_data)
        return docker_compose, docker_compose_override

    def _read_docker_compose(self):
        docker_compose_path = self._find_docker_compose_path()
        return self._read_file(docker_compose_path)

    def _find_docker_compose_path(self):
        for search_dir in self.search_path:
            for docker_compose_file in self.docker_compose_files:
                docker_compose_path = join(search_dir, docker_compose_file)
                if isfile(docker_compose_path):
                    return docker_compose_path

    def _read_file(self, file_path):
        with open(file_path, 'r') as f:
            contents = f.read()
        return contents

    def _render_docker_compose_override(self, config_data):
        docker_compose_override_path = self._find_docker_compose_override_path()
        template_dir, template_file = split(docker_compose_override_path)
        return self._render_template(template_dir, template_file, config_data)

    def _find_docker_compose_override_path(self):
        for search_dir in self.search_path:
            for docker_compose_override_file in self.docker_compose_override_files:
                template_file = join(search_dir, docker_compose_override_file)
                if isfile(template_file):
                    return template_file

    def _render_template(self, template_dir, template_file, template_data):
        template = Template(template_dir)
        return template.render(template_file, template_data)
