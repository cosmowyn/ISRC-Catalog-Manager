# Add a Manual macOS Keychain Reset

## Category

security

## Original prompt, cleaned

The app stores credentials in the OS keyring, but on macOS our app is ad hoc signed,
causing keyring failure after an update. Since we do not have a way to sign the app,
we need a way to clear the keyring associated with the app to refresh the stored
credentials after an update.

I did this manually using the attached Keychain command output.

Design a safe way to reset the keyring after an update (manual button action only).
This should reset the Keychain and allow a fresh start. **DO NOT remove any other
unrelated passwords.**

## Context preserved

- The recovery must be initiated only by an explicit button action; it must never run
  automatically during startup or an update.
- The existing production credential namespaces are the exact services
  `isrc-catalog-manager.database` and `isrc-catalog-manager.soundcloud`.
- The attached manual procedure used Apple's `/usr/bin/security` generic-password
  deletion command for those app-owned services.
- Unrelated passwords and other Keychain item classes must remain untouched.

## Redactions

The full attached Keychain dump was omitted because it included unrelated private
Keychain metadata, local paths, and account identifiers. No credential values or
unrelated Keychain records were copied into this archive.
