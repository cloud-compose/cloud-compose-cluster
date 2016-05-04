# docker_compose.run.sh 
cat << EOF > /tmp/docker-compose.yml
{{ docker_compose.yaml }}
EOF
cat << EOF > /tmp/docker-compose.override.yml
{{ docker_compose.override_yaml }}
EOF
