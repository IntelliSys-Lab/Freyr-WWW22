#! /bin/bash

#
# email-generation (eg)
#

cd /home/ubuntu/SAAF/python_email_generation/deploy

# Destroy and prepare build folder.
rm -rf build
mkdir build

# Install virtualenv
sudo docker run --rm -v "$PWD:/tmp" openwhisk/python3action bash \
  -c "cd tmp && virtualenv virtualenv && source virtualenv/bin/activate && pip3 install -r requirements.txt"

# Copy files to build folder.
cp -R ../src/* ./build
cp -R ../platforms/ibm/* ./build
cp -R virtualenv ./build
cd ./build
zip -X -r ./index.zip *

for i in {1..64}
do
  wsk -i action update eg_$i --kind python:3 --main main --memory $i index.zip
done
