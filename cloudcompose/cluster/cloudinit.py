from cloudcompose.template import Template

class CloudInit():
    def build(self, cloud_config):
        template = Template()
        print template.render('cluster', cloud_config)

