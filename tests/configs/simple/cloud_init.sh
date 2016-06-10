#!/bin/bash
# system.mounts.sh
mkfs -t ext4 /dev/xvdc
echo -e '/dev/xvdc\t/data/mongodb\text4\tdefaults,noatime\t0\t0' >> /etc/fstab
mkdir -p /data/mongodb
mount /data/mongodb
# docker_compose.run.sh 
cat << EOF > /tmp/docker-compose.yml
mongodb:
  container_name: mongodb 
  command: --shardsvr --replSet rs0 --dbpath /data/db
  ports:
    - "27018:27018"

EOF
cat << EOF > /tmp/docker-compose.override.yml
mongodb:
  image: washpost/mongodb:3.2
  extra_hosts:
    - "node0:10.0.10.10"
  volumes:
    - "/data/mongodb/mongodb:/data/db"
  environment:
    MONGODB_OPTIONS: "-h"
EOF
