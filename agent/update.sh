#! /bin/bash

# Update docker images
cd ../
# git remote set-url origin ${github_repo_link}
git pull
./gradlew distDocker

# Try to pull openwhisk python3ai image
docker pull your_username/actionloop-python-v3.6-ai

# Clean dangling images
cd agent
./clean_dangling_images.sh
