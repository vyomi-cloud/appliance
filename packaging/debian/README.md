# Debian / Ubuntu (.deb) package

Build via `fpm` from the release CI workflow — `fpm` is the cross-distro
package builder Ruby gem that converts a directory tree into a `.deb`.

The CI publishes the resulting `cloud-learn_<version>_all.deb` to the
GitHub Release and the repo at https://apt.cloudlearn.io.

## End-user install

```bash
# Add the apt repo
curl -fsSL https://apt.cloudlearn.io/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloudlearn.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudlearn.gpg] https://apt.cloudlearn.io stable main" \
  | sudo tee /etc/apt/sources.list.d/cloudlearn.list

# Install
sudo apt update
sudo apt install cloud-learn

# Run
cloud-learn up
```

## Direct .deb install (no repo)

```bash
wget https://github.com/cloudlearn/cloud-learn/releases/download/v1.0.0/cloud-learn_1.0.0_all.deb
sudo dpkg -i cloud-learn_1.0.0_all.deb
sudo apt-get install -f   # pulls in `multipass` etc.
```

## Build locally (for testing)

```bash
gem install fpm
bash packaging/debian/build-deb.sh 1.0.0
ls dist/cloud-learn_1.0.0_all.deb
```

See `packaging/debian/build-deb.sh` for the exact fpm invocation.
