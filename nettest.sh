#for net in {1..60}; do docker network create --subnet 172.18.${net}.0/24 -d bridge net${net} ; done
for net in {1..60}; do docker network create  -d bridge net${net} ; done

