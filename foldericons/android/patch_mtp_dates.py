from pathlib import Path
import re
header = next(Path('/build').glob('jmtpfs-*/src/MtpDevice.h'))
text = header.read_text()
text, count = re.subn(r'time_t\s+modificationdate;', 'time_t modificationdate = 0;', text)
if count != 1:
    raise RuntimeError('MTP timestamp field changed; refusing an unverified build')
header.write_text(text)
source = header.with_name('MtpDevice.cpp')
text = source.read_text()
text = text.replace('modificationdate = info.modificationdate;', 'modificationdate = info.modificationdate >= 0 && info.modificationdate <= 253402300799LL ? info.modificationdate : 0;')
source.write_text(text)
print('Initialized synthetic MTP dates and bounded reported dates')
