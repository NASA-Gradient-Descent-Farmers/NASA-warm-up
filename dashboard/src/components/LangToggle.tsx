import { useI18n } from '../i18n/index.tsx'

export function LangToggle({ className = '' }: { className?: string }) {
  const { t, lang, setLang } = useI18n()
  return (
    <div className={`segmented small ${className}`} role="group" aria-label={t('app.language')}>
      {(['es', 'en'] as const).map((code) => (
        <button key={code} type="button" aria-pressed={lang === code} lang={code} onClick={() => setLang(code)}>
          {code === 'es' ? 'Español' : 'English'}
        </button>
      ))}
    </div>
  )
}
