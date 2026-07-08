interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_ALLOWED_ORIGINS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
