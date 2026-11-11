# Custom folder icons

Place an exact file named `folder.ico` inside any folder. The FilePoint list displays that ICO as the folder's icon; folders without it retain the standard icon.

The service exposes the icon-enabled Files page on port `8704` and keeps the original page on port `8701` as a fallback. Icon discovery uses one authenticated batch request per open directory. ICO files are mounted nowhere new and are only read from their existing locations. Requests are checked against the signed-in FileBrowser user's source and scope before any icon is returned.

Sidebar icon readiness lives on the custom icon host, so native folder-selection
class updates cannot briefly reveal a duplicate default icon or rebuild loaded
artwork. Navigation only scrolls vertically when the selected row is outside the
sidebar viewport. Checks: `node foldericons/test_sidebar_navigation_icons.cjs`
and `node foldericons/test_sidebar_refresh.cjs`.

Opening a folder uses a 160 ms fade and subtle vertical entrance in the main
pane and newly expanded sidebar branches. Existing sidebar rows remain still,
and reduced-motion preferences disable these opening animations.

The server reads `/DATA/AppData/plexpoint-files-office/storage-map.json`, so storage names and host paths remain in one place. Restart `plexpoint-foldericons.service` after changing the map.

The checked-in `plexpoint-foldericons.service` grants the proxy write access only to those storage roots. That access is required for the Properties dialog to set the real Windows/DOS Hidden attribute; keep its `ReadWritePaths` entries in sync when adding or removing storage-map roots.

## Bulk rename

Select **2–100 items in one folder**, then choose **More (…) → Bulk rename…**.
Choose numbering, literal find-and-replace, or a prefix/suffix. The table previews
every name and preserves file extensions. Invalid names and collisions disable
the action; the folder is checked again immediately before applying changes.
Renames never overwrite a destination. Processing stops on failure or when the
panel is dismissed, after any in-flight rename completes; completed rows and a
summary distinguish partial success. Each successful rename uses the existing
operation history and can be undone individually with Ctrl+Z. Renamed items stay
selected after the listing refresh unless the user has made another selection.

Validation: live duplicate-name rejection, two-file numbering, restored selection
and two undo operations with unchanged file hashes.
Planner tests: `node foldericons/test_bulk_rename.cjs`.

## Upload window

The native uploader uses the Explorer glass theme with compact file/folder
buttons, secondary photo/video actions, and collapsible upload options below
the drop zone. Options support keyboard activation and labelled inputs. The
empty queue footer and duplicate technical summary are hidden; native upload,
folder targeting, progress, conflict handling and background notifications remain
in charge of transfers. The panel scrolls within the viewport on small screens.

The background notification waits for the native Completed status, rather than
100% bytes sent. New work clears old completion timers, and closing a busy upload
window returns it to the background. Conflict and directory rows count toward
queue state. Empty/cancelled queues clear their notification. Regression checks:
`node foldericons/test_upload_notification.cjs`.

## Office sync badges

Supported Office files with an active Microsoft session have a subtle, borderless
status beside their filename, using the file list's text colour. Click the
badge for the current status, last confirmed save time and existing sync controls.
**Saved** requires an active synced session with a confirmed save-back timestamp;
**Sync ready** means automatic sync is enrolled but no save-back has been confirmed.
Waiting, Retrying, Needs attention, Reconnect, Save back and Cleanup distinguish
the other session states. Files with no active session show no badge, including
files with historical save receipts. There is no loading or local-only badge.

Visible file rows refresh from the authenticated status endpoint every 15 seconds,
with at most three requests in flight. Background tabs pause polling. Failed
checks on previously active sessions show **Unavailable** and retry after 30 seconds.
The endpoint resolves the file identity server-side, including storage aliases.
The badges do not open Office or change sync settings on their own.

The custom Space quick-preview feature was removed on 22 October 2026. Bulk
rename and the existing file viewers remain available.

Validation: `node foldericons/test_office_sync_badges.cjs`; live inactive-file
badge suppression, Saved and Sync ready statuses, details and dismissal.

## Recycle bin and operation history

The customized Files page adds **Recycle Bin** as the final folder-style row in the sidebar tree. It uses the Windows system Recycle Bin artwork and changes between the empty and full icons. Opening it uses the normal Explorer details view in the main file pane, including the address bar, search box, resizable Name/Date deleted/Type/Size columns, and Back/Forward history. The toolbar restores selected items, permanently deletes selected items, or empties the bin. FileBrowser delete requests are moved into a private recycle area in the relevant storage root instead of being immediately erased.

File operations are journaled per signed-in user. `Ctrl+Z` undoes the latest move, rename, copy, create, edit, delete, or recycle-bin restore; `Ctrl+Y` and `Ctrl+Shift+Z` redo it. The More menu exposes the same Undo and Redo actions. History is capped at 100 operations and superseded snapshots are removed automatically.

The recycle and history directories are internal, are excluded from folder listings/search, and must remain writable by `plexpoint-foldericons.service`. After changing the proxy or its service definition, install the checked-in unit and restart it:

```sh
sudo install -m 0644 /DATA/AppData/plexpoint-files-office/foldericons/plexpoint-foldericons.service /etc/systemd/system/plexpoint-foldericons.service
sudo systemctl daemon-reload
sudo systemctl restart plexpoint-foldericons.service
```

## Microsoft web editing and recovery

### Desktop Office with automatic syncing

For DOCX, XLSX, XLSM, XLSB and PPTX, the file context menu also offers
**Open in Word/Excel/PowerPoint desktop app**. Office opens the authenticated
OneDrive editing copy using Microsoft's `ofe` protocol and keeps its normal
AutoSave behaviour. Office must be installed, signed into the connected Microsoft
account, and have AutoSave enabled. A browser may ask before opening the app.

The existing server worker checks enrolled files every 15 seconds and copies
stable cloud revisions to the original FilePoint file. No browser tab or manual
save-back step is required. The editing copy is retained for continuing work.
Right-click **Automatic sync status**, or use **More → Microsoft web sessions**,
to see the last save or a paused/retrying status. **Finish syncing** is optional:
close the desktop document first; it saves one final revision and conditionally
removes the editing copy.

An authenticated edit request grants background sync only for that file and its
resolved storage root. Browser credentials are not persisted. The grant survives
service restarts. Original moves/deletions, changed storage mappings, and separate
local edits pause syncing without overwriting or recreating anything. A cloud edit
during download is retried, and each successful replacement uses the existing
local revision backup. Connectivity failures retry with backoff. Existing manual
web sessions are not enrolled automatically. AutoSave cannot be promised for
arbitrary applications, legacy formats, encrypted files, or files that Office
opens read-only.

The desktop entry is gated on the server's `desktopAutoSync` capability so a
client update cannot expose an incomplete feature before the service restarts.

### Existing manual web workflow

Right-click a supported document to open one temporary OneDrive copy. After
Microsoft has finished saving, use **Save back & remove copy** in FilePoint.
The original is backed up before replacement. Cloud deletion is conditional on
the exact downloaded version; a newer cloud edit is never silently deleted.

- Failed cleanup retries in the server, not just while the page is open: up to
  six attempts with backoff. Changed cloud versions and expired connections stop
  automatic retries and preserve the copy. Reopening cancels pending cleanup.
- A saved timestamp remains available from **Last Microsoft save**. The toolbar's
  **More (…) → Microsoft web sessions** menu item lists this account's active copies and recent
  receipts, with open, save and cleanup actions. Lists respect current file scope.
- Opening a file already held by another FilePoint account requires an explicit
  competing-edit acknowledgement. This is a warning, not an exclusive editor lock.
- **Local version history** lists this account's pre-edit snapshots from its last
  100 undoable operations. It is not permanent archival backup: undo/redo, history
  expiry and new operations affect availability. Restoring first backs up the
  current file and refuses stale requests or active Microsoft copies. Snapshots
  are matched to the current path; history does not follow a later rename/move.
- Direct bridge formats: DOCX/ODT, XLSX/XLSB/XLSM/ODS, PPTX/PPSX/ODP. Browser feature
  limitations still apply; Excel macros do not run. Legacy, template and other
  conversion formats get instructions to create a separate modern-format copy.
  Existing legacy sessions are retained rather than saved back from a potentially
  unedited original cloud item. Download their edited converted copy manually.
- Outlook EML/MSG/OFT and OneNote files get appropriate manual workflow guidance,
  not automatic upload/save-back. MSG/OFT may require a Microsoft subscription.
- Launch feedback distinguishes a prepared copy, navigation requested, and popup
  failure. Cross-origin restrictions mean FilePoint cannot verify that Word itself
  finished loading; the test automation can inspect the actual Word tab separately.

Verification (16 October 2026): live Word open/save/cleanup; pending-save receipt;
session centre; competing-edit warning/cancel; older-version restore followed by
restoring the original SHA-256; CSV/Outlook guidance. Popup failures and temporary
cleanup failures are covered with controlled tests, not forced against Microsoft.
XLSB was validated against Microsoft's supported formats and bridge tests, not a
live binary-workbook round trip. Real user documents/sessions were not modified.
Final production run: all 96 Python tests passed on ZimaOS (no skips); five
JavaScript handoff scenarios plus feedback assertions passed on the workstation.
The hidden-attribute test harness explicitly covers both the raw fallback and
the installed native Samba implementation; no hidden-attribute runtime changes
were needed.

```sh
python3 -B -m unittest discover -s foldericons -p 'test_*.py'
node --check foldericons/client.js
node foldericons/test_microsoft_launch.cjs
```

Format references: [Excel](https://support.microsoft.com/en-us/excel/differences-between-using-a-workbook-in-the-browser-and-in-excel),
[PowerPoint](https://support.microsoft.com/en-us/powerpoint/how-certain-features-behave-in-web-based-powerpoint),
[Outlook](https://support.microsoft.com/en-us/outlook/mail/open-eml-msg-and-oft-files-in-new-outlook-and-outlook-on-the-web),
[OneNote](https://support.microsoft.com/en-us/onenote/onenote-for-web-help-and-learning/basic-tasks-in-onenote-for-the-web).

### Properties layout and independent Office windows (22 October 2026)

Properties uses a shared 36px control height, aligned metadata columns, consistent
section padding, and the existing theme colours. File details come before the
native checksum tools; CSS ordering leaves Vue's checksum nodes and handlers in
place. File types reuse the listing's readable label, with the raw MIME type
available as a tooltip. Narrow windows wrap checksum labels and keep the action
buttons within the dialog.

Native Word, Excel and PowerPoint file routes open a separate browser window
marked `officeWindow=1`, leaving the folder route mounted. Each launch uses a new
window; blocked pop-ups expose a manual link. Explicit child document windows
close themselves through the viewer close button. Direct file URLs retain their
normal route behavior. Router detection supports the production `__vue__` proxy
as well as Vue's app globals and component tree.

The resize repair observes the actual shell/listing content boxes and batches
native style/class updates before recalculating row clipping. Previously a
resize could cache row positions before desktop padding was restored, hiding
the first two files and clipping the third. Properties styling also uses its
persistent identity attribute because Vue resets the dialog class on resize.

Validation: JavaScript syntax, 33 layout regressions, Office window behavior,
row-clipping behavior, upload notifications and Office badge checks passed.
Live Properties verified at 1440x1000 and 390x844, including SHA-256 generation,
36px controls and no horizontal overflow. Reproduced the clipped rows, then
verified recovery across phone/desktop and short/tall resizing. All three Office
editor URLs loaded concurrently in independent tabs while the main folder
remained navigable. User-gesture popup requests were observed for all three
formats. The test host does not expose script-created popup windows, so actual
popup rendering/closing could not be directly inspected; editor loading was
checked by opening the requested URLs in tool-created tabs. Test documents were
not edited. The public client matches the saved source.

Run `node foldericons/test_office_windows.cjs` and
`node foldericons/test_row_clipping.cjs` for the behavior checks.

## Grouped upload notification

Folder uploads retain their nested structure in expandable groups. Each group
shows completed file counts and its current status; folders with errors open
when the error first appears. Folder creation jobs remain part of completion
tracking but do not appear as duplicate file cards or inflate the file counts.
PDF, Office, image, archive, media and text files use type-specific icons, with
fallback icons while Office artwork loads. Existing native upload actions still
handle pause, resume, cancellation and conflicts. Group expansion and file cards
remain mounted during progress updates.

Checks: `node foldericons/test_upload_groups_browser.cjs`,
`node foldericons/test_upload_cards.cjs`, and
`node foldericons/test_upload_notification.cjs`.
