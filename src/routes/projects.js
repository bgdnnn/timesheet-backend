import { Router } from "express";
import { PrismaClient } from "@prisma/client";
import auth from "../middleware/auth.js";

const router = Router();
const prisma = new PrismaClient();

router.get("/", auth, async (req, res) => {
  const projects = await prisma.project.findMany({
    where: { ownerId: req.user.id },
    orderBy: { createdAt: "desc" },
  });
  res.json(projects);
});

router.post("/", auth, async (req, res) => {
  const { name, description } = req.body;
  const project = await prisma.project.create({
    data: { name, description, ownerId: req.user.id },
  });
  res.json(project);
});

export default router;
