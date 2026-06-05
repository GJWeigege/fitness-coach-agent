export type UserProfile = {
  id: string;
  username: string;
  role: string;
  permissions: string[];
  is_active: boolean;
  created_at: string;
};
