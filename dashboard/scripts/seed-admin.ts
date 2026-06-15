// Create the super-admin dashboard user (idempotent) using the Supabase
// service-role key. Run: `npm run seed:admin`
import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY!;
const email = process.env.SUPER_ADMIN_EMAIL ?? "admin@diigoo.ai";
// No hardcoded credential default — fail loudly if it's not provided so a
// guessable password can never be seeded on a console that places billed calls.
const password = process.env.SUPER_ADMIN_PASSWORD;
if (!password) {
  console.error("seed-admin: SUPER_ADMIN_PASSWORD env var is required.");
  process.exit(1);
}

async function main() {
  const supabase = createClient(url, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const { error } = await supabase.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
  });
  if (error && !/already/i.test(error.message)) {
    console.error("seed-admin failed:", error.message);
    process.exit(1);
  }
  console.log(`super-admin ready: ${email}`);
}

main();
