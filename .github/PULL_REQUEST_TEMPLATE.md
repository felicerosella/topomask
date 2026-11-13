## What and why

<!-- What does this change and why is it needed? Link related issues. -->

## Checklist

- [ ] Tests cover the new behavior (`make check` passes locally)
- [ ] Only documentation values (RFC 5737, RFC 3849, RFC 2606) in code, tests and examples
- [ ] `CHANGELOG.md` updated under `Unreleased`
- [ ] Documentation updated if behavior or configuration changed

## Release only: manual check on clean Windows 10 and 11

- [ ] Installer runs without administrator rights; Start menu entry works; optional autostart works after sign-in
- [ ] Installing over the previous version keeps the data in `%APPDATA%\topomask`
- [ ] Uninstall from Settings → Apps removes the program and keeps the data
- [ ] Portable zip starts after unblocking
- [ ] SmartScreen behavior as documented
- [ ] Ctrl+Alt+A and Ctrl+Alt+R work and show a notification
- [ ] A hotkey already taken by another app shows a notification, the app keeps running
- [ ] Restored text does **not** appear in Win+V history
- [ ] Closing the window hides it; Quit exits
- [ ] A second instance shows the "already running" message
- [ ] Data is in `%APPDATA%\topomask`
- [ ] `topomask.log` contains no clipboard content or values
