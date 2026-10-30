; =====================================================================
;  SongGrabber – Windows-Installer (Inno Setup 6)
;  Wird von build.bat automatisch gebaut:  Setup\SongGrabber-Setup-<Version>.exe
;  Manuell:  ISCC.exe /DAppVersion=1.2.0 installer\SongGrabber.iss
; =====================================================================

#ifndef AppVersion
  #define AppVersion "1.11.0"
#endif
#define AppName      "SongGrabber"
#define AppPublisher "Pezhy"
#define AppExe       "SongGrabber.exe"

[Setup]
AppId={{37005CB9-DB3B-4F35-B50A-A8B8A7AD3F90}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
SourceDir=..
OutputDir=Setup
OutputBaseFilename=SongGrabber-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=assets\wizard-large.bmp,assets\wizard-large@2x.bmp
WizardSmallImageFile=assets\wizard-small.bmp,assets\wizard-small@2x.bmp
; Standard: nur für mich installieren (keine Admin-Rechte nötig) – im Dialog wählbar „für alle Benutzer“
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2/ultra64
SolidCompression=yes
; laufendes SongGrabber vor dem Update/Deinstallieren schließen
AppMutex=SongGrabber_by_Pezhy
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.Desktop=Desktop-Symbol erstellen
en.Desktop=Create a desktop shortcut
de.Kontext=Rechtsklick im Explorer: „Mit SongGrabber umwandeln“ (Audio- und Videodateien)
en.Kontext=Explorer right-click: "Convert with SongGrabber" (audio and video files)
de.Player=Als Musik-Player anbieten („Öffnen mit …“, Standard-Apps, Rechtsklick „Mit SongGrabber abspielen“)
en.Player=Offer as music player ("Open with", Default apps, right-click "Play with SongGrabber")
de.Extras=Zusätzlich:
en.Extras=Additional:
de.Starten=SongGrabber jetzt starten
en.Starten=Launch SongGrabber now
de.WebView=SongGrabber benötigt die Microsoft-Edge-WebView2-Laufzeit, die auf diesem PC fehlt.%n%nJetzt die kostenlose Installation von Microsoft herunterladen?
en.WebView=SongGrabber needs the Microsoft Edge WebView2 Runtime, which is missing on this PC.%n%nDownload the free installer from Microsoft now?
de.MusicTitle=Speicherort für deine Musik
en.MusicTitle=Where to save your music
de.MusicSub=Wo soll SongGrabber deine Musikstücke ablegen?
en.MusicSub=Where should SongGrabber save your music?
de.MusicText=SongGrabber sortiert alles automatisch nach Interpret / Album / Titel. Für ein Musik-Archiv eignet sich gut eine zweite Festplatte (z. B. D:\Musik) – Laufwerk C: bleibt so frei. Netzlaufwerk oder NAS: Pfad einfach eintippen, z. B. M:\Musik oder \\NAS\Musik. Den Ordner kannst du später jederzeit unter Einstellungen ändern.
en.MusicText=SongGrabber sorts everything by artist / album / title. A second drive (e.g. D:\Music) is a good place for a music archive. Network drive or NAS: just type the path, e.g. M:\Music or \\NAS\Music. You can change the folder later in the settings.
de.MusicStd=Standard verwenden
en.MusicStd=Use default
de.MusicNoDrive=Das Laufwerk %1 ist gerade nicht erreichbar.%n%nNetzlaufwerke sind während einer Installation mit Administratorrechten oft unsichtbar – SongGrabber selbst sieht sie später ganz normal.%n%nTrotzdem diesen Ordner verwenden? SongGrabber legt ihn beim ersten Start an.
en.MusicNoDrive=Drive %1 is not reachable right now.%n%nNetwork drives are often invisible while installing with administrator rights – SongGrabber itself will see them normally.%n%nUse this folder anyway? SongGrabber will create it on first start.
de.MusicBad=Bitte einen vollständigen Ordner angeben, z. B. D:\Musik oder \\NAS\Musik.
en.MusicBad=Please enter a full folder path, e.g. D:\Music or \\NAS\Music.
de.MusicNet=%1 ist dein Netzlaufwerk %2.%n%nDas Setup läuft mit Administratorrechten und sieht Netzlaufwerke deshalb nicht – SongGrabber selbst schon.%n%nStatt des Laufwerksbuchstabens lieber die Netzwerkadresse verwenden? Das funktioniert immer, auch wenn der Buchstabe einmal fehlt:%n%n%3%n%n„Nein“ behält %1.
en.MusicNet=%1 is your network drive %2.%n%nSetup runs with administrator rights and therefore cannot see network drives – SongGrabber itself can.%n%nUse the network address instead of the drive letter? This always works:%n%n%3%n%n"No" keeps %1.
de.DelData=Sollen auch die Einstellungen und der Bibliotheks-Zwischenspeicher gelöscht werden?%n%nDeine Musikdateien und Playlists bleiben in jedem Fall erhalten.
en.DelData=Also delete settings and library cache?%n%nYour music files and playlists are kept in any case.

[Tasks]
Name: "desktop";     Description: "{cm:Desktop}"; GroupDescription: "{cm:Extras}"
Name: "kontextmenue"; Description: "{cm:Kontext}"; GroupDescription: "{cm:Extras}"
Name: "player"; Description: "{cm:Player}"; GroupDescription: "{cm:Extras}"

[Files]
; das fertige Programm aus dem PyInstaller-Build (ohne Portable-Kennzeichnung und ohne Portable-Daten)
Source: "dist\SongGrabber\*"; DestDir: "{app}"; Excludes: "\portable.txt,\data,\data\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";                Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";          Filename: "{app}\{#AppExe}"; Tasks: desktop

[Registry]
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp4\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mkv\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webm\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mov\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.avi\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flv\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flv\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flv\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wmv\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wmv\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wmv\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4v\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4v\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4v\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mpg\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mpg\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mpg\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.vob\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.vob\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.vob\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.opus\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.opus\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.opus\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aiff\shell\SongGrabber"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber umwandeln"; Flags: uninsdeletekey; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aiff\shell\SongGrabber"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: kontextmenue
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aiff\shell\SongGrabber\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" ""%1"""; Tasks: kontextmenue

Root: HKA; Subkey: "Software\Classes\SongGrabber.Audio"; ValueType: string; ValueName: ""; ValueData: "Audiodatei (SongGrabber)"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SongGrabber.Audio\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SongGrabber.Audio\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\SongGrabber.Playlist"; ValueType: string; ValueName: ""; ValueData: "Playlist (SongGrabber)"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SongGrabber.Playlist\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SongGrabber.Playlist\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "SongGrabber"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "SongGrabber"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Musik-Player und Audio-Werkzeug"; Tasks: player
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "SongGrabber"; ValueData: "Software\SongGrabber\Capabilities"; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Audio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".mp3"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mp3"; ValueData: "SongGrabber.Audio"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.mp3\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Audio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".flac"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".flac"; ValueData: "SongGrabber.Audio"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.flac\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Audio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".wav"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wav"; ValueData: "SongGrabber.Audio"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wav\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.m4a\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Audio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".m4a"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m4a"; ValueData: "SongGrabber.Audio"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m4a\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.ogg\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Audio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".ogg"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ogg"; ValueData: "SongGrabber.Audio"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ogg\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.opus\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Audio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".opus"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".opus"; ValueData: "SongGrabber.Audio"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.opus\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.opus\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.opus\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.opus\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.aac\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Audio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".aac"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".aac"; ValueData: "SongGrabber.Audio"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.aac\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.wma\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Audio"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".wma"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wma"; ValueData: "SongGrabber.Audio"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.wma\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.m3u\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Playlist"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".m3u"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m3u"; ValueData: "SongGrabber.Playlist"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m3u\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m3u\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m3u\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m3u\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player
Root: HKA; Subkey: "Software\Classes\.m3u8\OpenWithProgids"; ValueType: string; ValueName: "SongGrabber.Playlist"; ValueData: ""; Flags: uninsdeletevalue; Tasks: player
Root: HKA; Subkey: "Software\Classes\Applications\SongGrabber.exe\SupportedTypes"; ValueType: string; ValueName: ".m3u8"; ValueData: ""; Tasks: player
Root: HKA; Subkey: "Software\SongGrabber\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m3u8"; ValueData: "SongGrabber.Playlist"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m3u8\shell\SongGrabberPlay"; ValueType: string; ValueName: ""; ValueData: "Mit SongGrabber abspielen"; Flags: uninsdeletekey; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m3u8\shell\SongGrabberPlay"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\SongGrabber.exe"",0"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m3u8\shell\SongGrabberPlay"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: player
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.m3u8\shell\SongGrabberPlay\command"; ValueType: string; ValueName: ""; ValueData: """{app}\SongGrabber.exe"" --play ""%1"""; Tasks: player

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:Starten}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\bin"
Type: dirifempty;     Name: "{app}"

[Code]
var
  MusicPage: TInputQueryWizardPage;
  MusicFirst: String;

const
  WV2 = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  OLDKEY = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8B784EE9-9C27-4C2B-883C-13982E655EAF}_is1';

{ Frühere Version unter dem alten Namen „AudioGrabber“ finden }
function OldUninstaller: String;
var
  S: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, OLDKEY, 'UninstallString', S) or RegQueryStringValue(HKLM, OLDKEY, 'UninstallString', S) then
    Result := RemoveQuotes(S);
end;

function WebView2Installed: Boolean;
var
  V: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WV2, 'pv', V) and (V <> '') and (V <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WV2, 'pv', V) and (V <> '') and (V <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WV2, 'pv', V) and (V <> '') and (V <> '0.0.0.0'));
end;

{ ---------- Musik-Ordner ---------- }
function MusicStandard: String;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\Music\SongGrabber';
end;

function MusicCurrent: String;
var
  S: String;
begin
  if RegQueryStringValue(HKCU, 'Software\SongGrabber', 'OutputDir', S) and (S <> '') then
    Result := S
  else
    Result := MusicStandard;
end;

procedure MusicStdClick(Sender: TObject);
begin
  MusicPage.Values[0] := MusicStandard;
end;

procedure MusicBrowseClick(Sender: TObject);
var
  D: String;
begin
  D := MusicPage.Values[0];
  if BrowseForFolder(CustomMessage('MusicSub'), D, True) then
    MusicPage.Values[0] := D;
end;

{ Eigenes Eingabefeld statt Ordner-Seite: die eingebaute Prüfung lehnt Netzwerkpfade ab,
  die das Setup mit Administratorrechten nicht sehen kann – SongGrabber selbst aber schon. }
procedure InitializeWizard;
var
  B, Br: TNewButton;
  E: TPasswordEdit;
begin
  MusicPage := CreateInputQueryPage(wpSelectDir, CustomMessage('MusicTitle'), CustomMessage('MusicSub'),
    CustomMessage('MusicText'));
  MusicPage.Add('', False);
  MusicFirst := MusicCurrent;
  MusicPage.Values[0] := MusicFirst;
  E := MusicPage.Edits[0];
  Br := TNewButton.Create(MusicPage);
  Br.Parent := MusicPage.Surface;
  Br.Caption := SetupMessage(msgButtonWizardBrowse);
  Br.Width := ScaleX(110);
  Br.Height := E.Height + ScaleY(4);
  Br.Left := MusicPage.SurfaceWidth - Br.Width;
  Br.Top := E.Top - ScaleY(2);
  Br.OnClick := @MusicBrowseClick;
  E.Width := Br.Left - E.Left - ScaleX(10);
  B := TNewButton.Create(MusicPage);
  B.Parent := MusicPage.Surface;
  B.Caption := CustomMessage('MusicStd');
  B.Width := ScaleX(160);
  B.Height := ScaleY(25);
  B.Left := E.Left;
  B.Top := E.Top + E.Height + ScaleY(12);
  B.OnClick := @MusicStdClick;
end;

{ Verbundenes Netzlaufwerk (z. B. M:) → \\Server\Freigabe aus dem Benutzerprofil }
function NetRemote(Drv: String): String;
var
  S: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, 'Network\' + Copy(Drv, 1, 1), 'RemotePath', S) then
    Result := S;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  P, Drv, Remote, Unc: String;
begin
  Result := True;
  if CurPageID = MusicPage.ID then
  begin
    P := Trim(MusicPage.Values[0]);
    if (Length(P) < 3) or ((Copy(P, 2, 2) <> ':\') and (Copy(P, 1, 2) <> '\\')) then
    begin
      MsgBox(CustomMessage('MusicBad'), mbError, MB_OK);
      Result := False;
      Exit;
    end;
    MusicPage.Values[0] := P;
    Drv := ExtractFileDrive(P);
    if (Length(Drv) = 2) and (not DirExists(Drv + '\')) then
    begin
      Remote := NetRemote(Drv);
      if Remote <> '' then
      begin
        Unc := Remote + Copy(P, 3, Length(P));
        if MsgBox(FmtMessage(CustomMessage('MusicNet'), [Drv, Remote, Unc]), mbConfirmation, MB_YESNO) = IDYES then
          MusicPage.Values[0] := Unc;
      end
      else if MsgBox(FmtMessage(CustomMessage('MusicNoDrive'), [Drv]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDNO then
        Result := False;
    end;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine + CustomMessage('MusicTitle') + ':' + NewLine + Space + MusicPage.Values[0];
  if MemoTasksInfo <> '' then
    Result := Result + NewLine + NewLine + MemoTasksInfo;
end;

procedure SaveMusicFolder;
var
  P: String;
begin
  P := MusicPage.Values[0];
  ForceDirectories(P);
  { nur übernehmen, wenn neu installiert oder im Setup geändert – sonst bleibt der Ordner aus SongGrabber }
  if (CompareText(P, MusicFirst) <> 0) or (not FileExists(ExpandConstant('{userappdata}\SongGrabber\settings.json'))) then
  begin
    RegWriteStringValue(HKCU, 'Software\SongGrabber', 'SetupOutputDir', P);
    RegWriteStringValue(HKCU, 'Software\SongGrabber', 'OutputDirStamp', GetDateTimeString('yyyymmddhhnnss', #0, #0));
  end;
  RegWriteStringValue(HKCU, 'Software\SongGrabber', 'OutputDir', P);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Old: String;
begin
  if CurStep = ssInstall then
  begin
    Old := OldUninstaller;
    if (Old <> '') and FileExists(Old) then
      Exec(Old, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
  if CurStep = ssPostInstall then
    SaveMusicFolder;
  if (CurStep = ssPostInstall) and (not WizardSilent) and (not WebView2Installed) then
    if MsgBox(CustomMessage('WebView'), mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://go.microsoft.com/fwlink/p/?LinkId=2124703', '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{userappdata}\SongGrabber');
    if DirExists(Data) and (not UninstallSilent) then
      if MsgBox(CustomMessage('DelData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
