import { useState } from 'react'
import { Download, Terminal } from 'lucide-react'
import type { CalculationTrace as CalculationTraceData } from '../types/api'

export function CalculationTrace({ trace }: { trace?: CalculationTraceData }) {
  const [format, setFormat] = useState<'txt' | 'json'>('txt')
  if (!trace) return null

  const download = () => {
    const content = format === 'json'
      ? JSON.stringify(trace, null, 2)
      : [
        `Пошаговый лог прогноза · ${trace.company_id} · ${trace.horizon_days} дней`,
        `Сформирован: ${trace.generated_at}`,
        '',
        ...trace.steps.map((step) => `[${step.timestamp}] Шаг ${step.step}. ${step.title}\n${step.details}`),
      ].join('\n\n')
    const url = URL.createObjectURL(new Blob([content], { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/plain;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `forecast-${trace.company_id}-${trace.horizon_days}d.${format}`
    link.click()
    URL.revokeObjectURL(url)
  }

  return <details className="card calculation-trace">
    <summary><Terminal size={17} />Пошаговый лог построения прогноза <span>{trace.steps.length} этапов · {new Date(trace.generated_at).toLocaleString('ru-RU')}</span></summary>
    <div className="trace-toolbar">
      <label>Формат файла<select aria-label="Формат лога" value={format} onChange={(event) => setFormat(event.target.value as 'txt' | 'json')}><option value="txt">TXT</option><option value="json">JSON</option></select></label>
      <button className="button secondary" type="button" onClick={download}><Download size={15} />Скачать лог расчета</button>
    </div>
    <ol className="trace-timeline">{trace.steps.map((step) => <li key={step.step}><div className="trace-step-head"><strong>Шаг {step.step}. {step.title}</strong><time>{new Date(step.timestamp).toLocaleString('ru-RU')}</time></div><pre>{step.details}</pre></li>)}</ol>
  </details>
}
