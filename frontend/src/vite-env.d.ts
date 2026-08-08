/// <reference types="vite/client" />

/** Version du dépôt, injectée au build depuis le fichier VERSION (voir vite.config.ts). */
declare const __APP_VERSION__: string
/** Commit construit, abrégé (suffixé `-dirty` si l'arbre était modifié). */
declare const __APP_COMMIT__: string
/** Horodatage UTC du build, au format `AAAA-MM-JJTHH:MMZ`. */
declare const __APP_BUILT_AT__: string
