import ctypes,os
libc=ctypes.CDLL(None,use_errno=True)
for prefix in ['/media','/DATA/.media','/var/lib/casaos_data/.media']:
    for name in ['FilePoint-Devices','FilePoint-Phones']:
        root=(prefix+'/'+name).encode()
        result=libc.mount(None,root,None,(1<<18)|(1<<14),None)
        print('private',root.decode(),result,ctypes.get_errno(),flush=True)
        result=libc.umount2(root,2)
        print('detach',root.decode(),result,ctypes.get_errno(),flush=True)