import { describe, expect, it } from 'vitest'
import { addDaysToDate, parseEventText } from './eventTextParser'

describe('parseEventText', () => {
  it('parses an incoming payment with an explicit Russian date', () => {
    expect(parseEventText('Клиент оплатит 350000 15.11.2026 по договору', '2026-10-24')).toEqual({
      date: '2026-11-15', amount: 350000, direction: 'поступление',
      category: 'Выручка и поступления от клиентов', event_type: 'Счёт клиенту',
    })
  })

  it('parses grouped amounts, relative dates, and payment categories', () => {
    expect(parseEventText('Оплата аренды офиса 120 000 завтра', '2026-10-24')).toMatchObject({
      date: '2026-10-25', amount: 120000, direction: 'списание', category: 'Аренда',
    })
    expect(parseEventText('Налоговый платёж 250 тыс через 7 дней', '2026-10-24')).toMatchObject({
      date: '2026-10-31', amount: 250000, category: 'Налоги и обязательные платежи',
    })
  })

  it('anchors default dates and relative phrases to the last actual operation date', () => {
    expect(addDaysToDate('2025-12-31', 3)).toBe('2026-01-03')
    expect(parseEventText('Оплата аренды офиса 120 000 завтра', '2025-12-31').date).toBe('2026-01-01')
  })
})