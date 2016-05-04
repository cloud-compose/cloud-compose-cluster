# docker_compose.run.sh 
cat << EOF > /root/docker-compose.yml
{{ docker_compose.yaml }}
EOF
cat << EOF > /root/docker-compose.override.yml
{{ docker_compose.override_yaml }}
EOF
