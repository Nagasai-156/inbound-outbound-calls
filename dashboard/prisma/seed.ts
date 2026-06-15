// Seed the single AgentConfig row so the agent + dashboard always have
// defaults to work with. Run: `npm run db:seed`.
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  await prisma.agentConfig.upsert({
    where: { id: "default" },
    update: {},
    create: { id: "default", updatedBy: "seed" },
  });
  console.log("AgentConfig 'default' ensured.");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
