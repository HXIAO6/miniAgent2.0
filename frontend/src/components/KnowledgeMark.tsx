/** 书页与书签构成知识库标识，使用本地矢量图形，无外部图片请求。 */
export function KnowledgeMark({ className = "" }: { className?: string }) {
  return <svg className={className} viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <path d="M10 8h22l7 7v25H10V8Z" fill="currentColor" opacity=".12" />
    <path d="M10 8h22l7 7v25H10V8Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    <path d="M29 8v15l-5-3-5 3V8M17 30h15M17 35h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}
