interface Props {
  status?: string
}

/**
 * T7-14: 打字指示器
 * 在 AI 回答時顯示動態波浪效果及狀態文字
 */
export default function TypingIndicator({ status }: Props) {
  return (
    <div className="flex animate-fade-in justify-start">
      <div className="card rounded-bl-md px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">
            <span className="h-2 w-2 animate-bounce rounded-full bg-accent/70" style={{ animationDelay: '0ms' }} />
            <span className="h-2 w-2 animate-bounce rounded-full bg-accent/70" style={{ animationDelay: '150ms' }} />
            <span className="h-2 w-2 animate-bounce rounded-full bg-accent/70" style={{ animationDelay: '300ms' }} />
          </div>
          {status && (
            <span className="text-sm text-muted">{status}</span>
          )}
        </div>
      </div>
    </div>
  )
}
