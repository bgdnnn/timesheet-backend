import { Router } from "express";
import { PrismaClient } from "@prisma/client";
import auth from "../middleware/auth.js";

const router = Router();
const prisma = new PrismaClient();

router.get("/", auth, async (req, res) => {
  const sheets = await prisma.timesheet.findMany({
    where: { userId: req.user.id },
    include: { project: true },
    orderBy: { date: "desc" },
  });
  res.json(sheets);
});

router.post("/", auth, async (req, res) => {
  const { projectId, date, hours, note } = req.body;
  const sheet = await prisma.timesheet.create({
    data: {
      userId: req.user.id,
      projectId,
      date: new Date(date),
      hours,
      note,
    },
  });
  res.json(sheet);
});

router.put("/:id", auth, async (req, res) => {
  const { id } = req.params;
  const { projectId, date, hours, note } = req.body;
  const sheet = await prisma.timesheet.update({
    where: { id: Number(id), userId: req.user.id },
    data: {
      projectId,
      date: new Date(date),
      hours,
      note,
    },
  });
  res.json(sheet);
});

router.delete("/:id", auth, async (req, res) => {
  const { id } = req.params;
  await prisma.timesheet.delete({
    where: { id: Number(id), userId: req.user.id },
  });
  res.sendStatus(204);
});

export default router;
