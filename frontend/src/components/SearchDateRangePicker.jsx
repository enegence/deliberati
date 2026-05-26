import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addMonths(date, delta) {
  return new Date(date.getFullYear(), date.getMonth() + delta, 1);
}

function formatDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseDateKey(value) {
  if (!value) {
    return null;
  }

  const candidate = new Date(`${value}T00:00:00`);
  return Number.isNaN(candidate.getTime()) ? null : candidate;
}

function formatRangeLabel(value) {
  if (!value.start) {
    return 'Any date';
  }

  const formatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });
  const startDate = parseDateKey(value.start);
  const endDate = parseDateKey(value.end);

  if (!startDate) {
    return 'Any date';
  }
  if (!endDate) {
    return `From ${formatter.format(startDate)}`;
  }
  if (value.start === value.end) {
    return formatter.format(startDate);
  }

  return `${formatter.format(startDate)} to ${formatter.format(endDate)}`;
}

function buildCalendarDays(monthDate) {
  const firstDayOfMonth = startOfMonth(monthDate);
  const gridStart = new Date(firstDayOfMonth);
  gridStart.setDate(gridStart.getDate() - gridStart.getDay());

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + index);
    return date;
  });
}

export default function SearchDateRangePicker({ value, onChange }) {
  const [isOpen, setIsOpen] = useState(false);
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const selectedStart = parseDateKey(value.start);
    return startOfMonth(selectedStart || new Date());
  });
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  const popoverRef = useRef(null);
  const [popoverStyle, setPopoverStyle] = useState(null);
  const calendarDays = useMemo(() => buildCalendarDays(visibleMonth), [visibleMonth]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const updatePopoverPosition = () => {
      const buttonBounds = buttonRef.current?.getBoundingClientRect();
      if (!buttonBounds) {
        return;
      }

      const popoverWidth = 280;
      const viewportPadding = 12;
      const desiredLeft = buttonBounds.right - popoverWidth;
      const maxLeft = window.innerWidth - popoverWidth - viewportPadding;
      const left = Math.min(Math.max(viewportPadding, desiredLeft), maxLeft);
      const top = Math.min(
        buttonBounds.bottom + 10,
        window.innerHeight - viewportPadding
      );

      setPopoverStyle({
        position: 'fixed',
        top: `${top}px`,
        left: `${left}px`,
        zIndex: 2000,
      });
    };

    const handlePointerDown = (event) => {
      if (
        !rootRef.current?.contains(event.target)
        && !popoverRef.current?.contains(event.target)
      ) {
        setIsOpen(false);
      }
    };

    const rafId = window.requestAnimationFrame(updatePopoverPosition);
    window.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('resize', updatePopoverPosition);
    window.addEventListener('scroll', updatePopoverPosition, true);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('resize', updatePopoverPosition);
      window.removeEventListener('scroll', updatePopoverPosition, true);
    };
  }, [isOpen]);

  const handleDayClick = (dayKey) => {
    if (!value.start || value.end) {
      onChange({ start: dayKey, end: '' });
      return;
    }

    const nextStart = value.start <= dayKey ? value.start : dayKey;
    const nextEnd = value.start <= dayKey ? dayKey : value.start;
    onChange({ start: nextStart, end: nextEnd });
  };

  const isInRange = (dayKey) => {
    if (!value.start || !value.end) {
      return false;
    }
    return dayKey >= value.start && dayKey <= value.end;
  };

  const isRangeEdge = (dayKey) => dayKey === value.start || dayKey === value.end;

  return (
    <div className="search-date-picker" ref={rootRef}>
      <button
        ref={buttonRef}
        className={`conversation-search-calendar-button ${
          value.start ? 'active' : ''
        }`}
        type="button"
        aria-label="Filter search by date"
        title={formatRangeLabel(value)}
        onClick={() => {
          setIsOpen((open) => {
            const nextOpen = !open;
            if (nextOpen) {
              const selectedStart = parseDateKey(value.start);
              setVisibleMonth(startOfMonth(selectedStart || new Date()));
            }
            return nextOpen;
          });
        }}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 7h16M4 7v12a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V7M4 7V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2M8 3v4M16 3v4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {isOpen && popoverStyle && createPortal((
        <div
          className="conversation-search-calendar-popover"
          ref={popoverRef}
          style={popoverStyle}
        >
          <div className="conversation-search-calendar-header">
            <button
              className="conversation-search-calendar-nav"
              type="button"
              aria-label="Previous month"
              onClick={() => setVisibleMonth((month) => addMonths(month, -1))}
            >
              ‹
            </button>
            <div className="conversation-search-calendar-month">
              {visibleMonth.toLocaleDateString(undefined, {
                month: 'long',
                year: 'numeric',
              })}
            </div>
            <button
              className="conversation-search-calendar-nav"
              type="button"
              aria-label="Next month"
              onClick={() => setVisibleMonth((month) => addMonths(month, 1))}
            >
              ›
            </button>
          </div>

          <div className="conversation-search-calendar-grid conversation-search-calendar-grid-weekdays">
            {WEEKDAY_LABELS.map((label) => (
              <div key={label} className="conversation-search-calendar-weekday">
                {label}
              </div>
            ))}
          </div>

          <div className="conversation-search-calendar-grid">
            {calendarDays.map((day) => {
              const dayKey = formatDateKey(day);
              const inCurrentMonth = day.getMonth() === visibleMonth.getMonth();
              const selected = isRangeEdge(dayKey);
              const inRange = isInRange(dayKey);

              return (
                <button
                  key={dayKey}
                  className={`conversation-search-calendar-day ${
                    inCurrentMonth ? '' : 'outside-month'
                  } ${selected ? 'selected' : ''} ${inRange ? 'in-range' : ''}`}
                  type="button"
                  onClick={() => handleDayClick(dayKey)}
                >
                  {day.getDate()}
                </button>
              );
            })}
          </div>

          <div className="conversation-search-calendar-footer">
            <div className="conversation-search-calendar-summary">
              {formatRangeLabel(value)}
            </div>
            <div className="conversation-search-calendar-help">
              {!value.start || value.end
                ? 'Click once to set a start date.'
                : 'Click again to set the finish date.'}
            </div>
            {value.start && (
              <button
                className="conversation-search-calendar-reset"
                type="button"
                onClick={() => onChange({ start: '', end: '' })}
              >
                Clear dates
              </button>
            )}
          </div>
        </div>
      ), document.body)}
    </div>
  );
}
