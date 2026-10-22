import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/_authed/workflows_/$workflowId/')({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: '/workflows/$workflowId/overview',
      params: { workflowId: params.workflowId },
    })
  },
})
