# How iOS stores home screen positions

This is an excerpt of the shape SpringBoard saves in `Library/SpringBoard/IconState.plist`,
seen on iOS 27.0.1, with made-up IDs. You can see your own file with a layout-file-only backup (see `references/troubleshooting.md`, step 4 of "After an iOS update").

```text
listUniqueIdentifiers: [ "PAGE-1-UUID", "PAGE-2-UUID", ... ]   one ID per home screen page
iconLists: [ [ <widget dict>, "com.example.app1", ..., <folder dict> ], ... ]
  folder dict: { displayName: "Utilities", listType: "folder",
                 uniqueIdentifier: "FOLDER-UUID", listUniqueIdentifiers: [...], iconLists: [...] }
listMetadata:
  "PAGE-1-UUID":
    fixedLocationsGridColumns: 4
    fixedLocationsGridRows: 6
    fixedLocations:
      "com.example.app1": 20                 an app: keyed by bundle ID
      "folder:FOLDER-UUID": 23               a folder: "folder:" + its uniqueIdentifier
ignored: [ "com.example.applibraryonly" ]   apps removed from the home screen (App Library only)
```

Only items placed after a gap get a `fixedLocations` entry. Everything else fills the first
free slot in list order. `push.py --pin` writes this shape through the layout service. It
assigns each pinned folder a new `uniqueIdentifier`, which SpringBoard keeps.
