# FilePoint Server

FilePoint's ZimaOS server: the Python API and web proxy, the browser UI, the FileBrowser Quantum and ONLYOFFICE configuration templates, and the optional removable storage and Android MTP helpers.

The [Windows app source and installers](https://github.com/JNathan34/FilePoint-Windows-Downloads) are maintained in a separate repository. In the Windows app, sign in with the URL that serves the FilePoint proxy.

- `foldericons/server.py`, `native_writes.py`, `client.js`, and `connected_storage_client.js` implement the API and web experience. The tests and UI assets live alongside them.
- `docker-compose.example.yml` and `filebrowser/config.example.yaml` describe the container stack. FileBrowser Quantum and ONLYOFFICE are pulled as container images.
- `foldericons/plexpoint-foldericons.service` and `foldericons/filepoint-storage.service` describe the host services. See [connected storage](foldericons/CONNECTED-STORAGE.md) for the broker and optional Android container. The Android image fetches upstream jmtpfs source and applies the tracked patch when it builds.

## Configure an instance

Use a Linux host with Docker Compose, systemd, and Python 3.11 or later. ZimaOS normally uses `/DATA/AppData/plexpoint-files-office` for the application directory. Use a separate host or test instance to try the example Compose project; for an existing ZimaOS deployment, use the Compose project managed by CasaOS.

1. Copy `docker-compose.example.yml` to `docker-compose.yml`. Set `FILEPOINT_DATA_DIR`, `FILEPOINT_STORAGE_DIR`, and `FILEPOINT_BIND_IP` in a local `.env` as needed. Edit the bind mounts to match the server's actual storage. Create the mount points and runtime directories before starting the stack.
2. Copy `filebrowser/config.example.yaml` to `filebrowser/config.yaml` and `office.env.example` to `office.env` in the application directory. Set the FileBrowser and ONLYOFFICE URLs. Generate unique values for the admin password, FileBrowser signing key, and ONLYOFFICE JWT secret. Set the same JWT secret in both ONLYOFFICE and the FileBrowser integration. Restrict access to both local config files.
3. Copy `storage-map.example.json` to `storage-map.json` and match its names and host paths to the FileBrowser sources and mounts. To opt into native writes, copy `native-write-sources.example.json` to `native-write-sources.json` and list only the sources that should support native writes. Adjust the systemd unit or a local drop-in for the app directory, bind and upstream addresses, and writable directories. The proxy needs the `home-layout`, `hidden-items`, `folder-material-icons`, `microsoft-bridge`, and `operation-history` directories.
4. Validate Compose with `docker compose config --quiet` on the target host before starting it. Install the proxy service once the upstream is reachable. Route the public FilePoint URL through a TLS reverse proxy to FilePoint on port 8704. If the reverse proxy runs off host, set the FilePoint listener and firewall rules for that host. Keep the FileBrowser upstream and host administration interfaces private.
5. Configure optional integrations separately. The Microsoft bridge uses local OAuth or rclone configuration; connected storage requires the host broker. Leave the Android helper off until it can be tested with a physical phone on the target host.

Live configuration, account databases, storage contents, session and verification data, and server backups are outside this repository. Keep those in your private ZimaOS backup process if you need to restore the entire instance.

## Checks

```sh
python3 -B -m unittest discover -s foldericons -p 'test_*.py'
node --check foldericons/client.js
node --check foldericons/connected_storage_client.js
```

Run the Python suite on Linux: the native file tests rely on Linux filesystem operations. Browser and live HTTP checks under `foldericons/` have additional setup requirements and some require a running test instance.
