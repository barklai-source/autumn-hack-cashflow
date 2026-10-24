export type ParsedEventText = {
  date: string
  amount: number
  direction: 'поступление' | 'списание'
  category: string
  event_type: string
}

export function addDaysToDate(dateText: string, days: number): string {
  const date = new Date(`${dateText.slice(0, 10)}T00:00:00`)
  date.setDate(date.getDate() + days)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function toIsoDate(year: string, month: string, day: string): string {
  const parsed = new Date(Number(year), Number(month) - 1, Number(day))
  if (parsed.getFullYear() !== Number(year) || parsed.getMonth() !== Number(month) - 1 || parsed.getDate() !== Number(day)) {
    throw new Error('Дата в фразе указана некорректно.')
  }
  return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
}

export function parseEventText(text: string, referenceDate: string): ParsedEventText {
  const normalized = text.toLocaleLowerCase('ru-RU')
  let date: string | null = null
  const isoDate = normalized.match(/(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)/)
  const ruDate = normalized.match(/(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)/)
  if (isoDate) date = toIsoDate(isoDate[1], isoDate[2], isoDate[3])
  else if (ruDate) date = toIsoDate(ruDate[3], ruDate[2], ruDate[1])
  else if (normalized.includes('послезавтра')) date = addDaysToDate(referenceDate, 2)
  else if (normalized.includes('завтра')) date = addDaysToDate(referenceDate, 1)
  else {
    const daysFromNow = normalized.match(/через\s+(\d+)\s+д(?:ень|ня|ней)/)
    if (daysFromNow) date = addDaysToDate(referenceDate, Number(daysFromNow[1]))
  }
  if (!date) throw new Error('Не удалось распознать дату. Укажите день в фразе.')

  const amountText = normalized
    .replace(/(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)/g, ' ')
    .replace(/(?<!\d)\d{1,2}\.\d{1,2}\.\d{4}(?!\d)/g, ' ')
    .replace(/послезавтра|завтра|через\s+\d+\s+д(?:ень|ня|ней)/g, ' ')
  const amountMatch = amountText.match(/(\d[\d\s\u00a0\u202f]*(?:[,.]\d+)?)\s*(млрд\.?|миллиард(?:а|ов)?|млн\.?|миллион(?:а|ов)?|тыс\.?|тысяч(?:а|и)?|тр\.?|т\.?\s*р\.?|руб(?:лей|ля)?|₽)?/i)
  if (!amountMatch) throw new Error('Не удалось распознать сумму.')
  const amountNumber = Number(amountMatch[1].replace(/[\s\u00a0\u202f]/g, '').replace(',', '.'))
  const unit = (amountMatch[2] ?? '').toLocaleLowerCase('ru-RU')
  const multiplier = /млрд|миллиард/.test(unit) ? 1_000_000_000
    : /млн|миллион/.test(unit) ? 1_000_000
      : /тыс|тысяч|тр\.?|т\.?\s*р/.test(unit) ? 1_000 : 1
  const amount = amountNumber * multiplier
  if (!Number.isFinite(amount) || amount <= 0) throw new Error('Сумма должна быть больше нуля.')

  const incomingWords = ['клиент', 'покупатель', 'придет', 'придёт', 'оплатит', 'выручк', 'аванс']
  const direction = incomingWords.some((word) => normalized.includes(word)) ? 'поступление' : 'списание'
  const matches = (words: string[]) => words.some((word) => normalized.includes(word))

  let category: string
  let event_type: string
  if (matches(['аренд', 'коммунал', 'электроэнерг'])) {
    category = 'Аренда'
    event_type = 'Аренда'
  } else if (matches(['налог', 'енп', 'фнс', 'ндфл'])) {
    category = 'Налоги и обязательные платежи'
    event_type = 'Налоговый платёж (ввод пользователя)'
  } else if (matches(['зарплат', 'заработн', 'оплата труда'])) {
    category = 'Фонд оплаты труда'
    event_type = 'Зарплата'
  } else if (matches(['поставщик', 'поставк', 'закуп', 'упд', 'товар'])) {
    category = 'Закупки и поставщики'
    event_type = 'Счёт поставщика'
  } else if (matches(['кредит', 'лизинг', 'овердрафт'])) {
    category = 'Кредиты и проценты'
    event_type = 'Кредит или лизинг'
  } else if (direction === 'поступление') {
    category = 'Выручка и поступления от клиентов'
    event_type = 'Счёт клиенту'
  } else {
    category = 'Прочие расходы'
    event_type = 'Пользовательское событие'
  }

  return { date, amount, direction, category, event_type }
}