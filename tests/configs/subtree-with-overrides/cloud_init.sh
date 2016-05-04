#!/bin/bash
# system.mounts.sh
mkfs -t ext4 /dev/xvdc
echo -e '/dev/xvdc\t/data/mongodb\text4\tdefaults,noatime\t0\t0' >> /etc/fstab
mkdir -p /data/mongodb
mount /data/mongodb
# docker_compose.run.sh 
cat << EOF > /root/docker-compose.yml
mongodb:
  container_name: mongodb 
  command: --shardsvr --replSet rs0 --dbpath /data/db
  ports:
    - "27018:27018"

EOF
cat << EOF > /root/docker-compose.override.yml
mongodb:
  image: washpost/mongodb:3.3
  extra_hosts:
    - "node0:10.0.11.10"
  volumes:
    - "/data/mongodb/mongodb:/data/db"
EOF
