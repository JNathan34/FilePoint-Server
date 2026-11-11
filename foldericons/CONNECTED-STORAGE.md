# Connected storage

FilePoint discovers USB and removable storage every three seconds. ZimaOS mounts the device first; the storage broker creates private bind mirrors under `/media/FilePoint-Devices`. The file server receives these through its existing Home source at `Connected devices`. Device metadata uses the same authenticated Home path scopes as file access.

Home shows each device in a Connected devices section between Drives and Folders, with its icon, used-space bar, and free/total capacity. Connected devices appears immediately after 8TB HDD in the sidebar. The former fixed Sandisk USB source has been replaced by discovery. Files on the physical devices are not moved.

EFI and Microsoft Reserved partitions are hidden. Small FAT boot partitions up to 128 MiB are hidden when the same disk also has a larger data partition. A standalone small USB remains visible. Unmounted BitLocker and LUKS volumes use the supplied lock icon and cannot be opened until unlocked on the server. FilePoint does not unlock or format storage.

Icons are stored in `assets/devices` and served from the whitelisted `/__foldericons/device-icon?kind=` endpoint. USB and phone icons are selected for detected devices; unknown kinds use Device.ico. Camera, video, printer, and computer artwork is available for matching device integrations. Devices without storage are not exposed as drives.

**Phone support is currently stopped, with automatic restart disabled, following recovery from a propagated-mount discovery loop. Keep it stopped until a supervised phone test passes.** Discovery now accepts only direct mounts under `/media/FilePoint-Phones`, and the API/UI limit device entries to 64.

Android MTP support uses the local `filepoint-android` container. Connect the phone, unlock it, and choose File transfer on the phone. The helper mounts accessible storage at `/media/FilePoint-Phones`, then the broker exposes it. Capacity is displayed when the phone reports it; otherwise the UI states that storage information is unavailable. Physical Android testing remains outstanding.

## Maintenance

- Host service: `filepoint-storage.service`; source: `storage_broker.py` and `storage_devices.py`.
- Android helper: `android/compose.yml` and `android/phone_bridge.py`.
- Registry: `../connected-storage.json`; stable folder aliases: `../connected-storage-aliases.json`.
- Host staging roots are separate shared tmpfs mounts. Do not replace them with self-bind mounts or put the broker in a private mount namespace.
- Production FileBrowser compose is managed by CasaOS. Use its actual project and config labels from `docker inspect plexpoint-files`, rather than starting a second project from the workspace compose.
- Unplugging removes only the mirror mount and empty mountpoint. The broker never recursively removes device contents.
- Check with `python3 -B -m unittest discover -s foldericons -p 'test_*.py'` from the project root.