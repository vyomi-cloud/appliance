# Debian / Ubuntu (.deb) package

Build via `fpm` from the release CI workflow — `fpm` is the cross-distro
package builder Ruby gem that converts a directory tree into a `.deb`.

The CI publishes the resulting `vyomi_<version>_all.deb` to the
GitHub Release and the repo at https://apt.vyomi.cloud.

## End-user install

```bash
# Add the apt repo
curl -fsSL https://apt.vyomi.cloud/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/vyomi.gpg
echo "deb [signed-by=/usr/share/keyrings/vyomi.gpg] https://apt.vyomi.cloud stable main" \
  | sudo tee /etc/apt/sources.list.d/cloudlearn.list

# Install
sudo apt update
sudo apt install vyomi

# Run
vyomi up
```

## Direct .deb install (no repo)

```bash
wget https://github.com/vyomi-cloud/appliance/releases/download/v3.0.33/vyomi_3.0.33_all.deb
sudo dpkg -i vyomi_3.0.33_all.deb
sudo apt-get install -f   # pulls in `multipass` etc.
```

## Build locally (for testing)

```bash
gem install fpm
bash packaging/debian/build-deb.sh 1.0.0
ls dist/vyomi_3.0.33_all.deb
```

See `packaging/debian/build-deb.sh` for the exact fpm invocation.
