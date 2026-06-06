# shaqcast

Minimal GUI tool (wxPython) that listens to a selected Windows output device (loopback), recognizes the current track (Shazam), and updates "Now Playing" metadata for:

- Shoutcast (one or more SIDs)
- Icecast (one or more mountpoints)

For Icecast, enter multiple mountpoints separated by commas, semicolons, or new lines,
for example `/stream,/stream2`. Use the Icecast user that is allowed to call
`/admin/metadata`; on some servers this is `admin`, not `source`.
