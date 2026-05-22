import { ApprovalQueue } from './ApprovalQueue';

export function ApprovalQueuePage(): JSX.Element {
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold mb-4">Pending approvals</h1>
      <ApprovalQueue />
    </div>
  );
}
