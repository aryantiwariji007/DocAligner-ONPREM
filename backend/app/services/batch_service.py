import asyncio
import time
from typing import List, Dict, Any, Callable
from backend.app.services.ai_service import ai_service
from pydantic import BaseModel

class ValidationTask(BaseModel):
    task_id: str
    section_text: str
    global_context: Dict[str, Any]
    relevant_standard_text: str
    future: Any # asyncio.Future to return result to caller

class BatchValidationService:
    def __init__(self, batch_size: int = 3, max_wait_ms: int = 50):
        self.batch_size = batch_size
        self.max_wait_ms = max_wait_ms
        self._queue: List[ValidationTask] = []
        self._lock = asyncio.Lock()
        self._batch_task: asyncio.Task = None

    async def schedule_validation(self, task_id: str, section_text: str, global_context: Dict[str, Any], relevant_standard_text: str) -> Dict[str, Any]:
        """Add a section to the batch queue and wait for its result."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        task = ValidationTask(
            task_id=task_id,
            section_text=section_text,
            global_context=global_context,
            relevant_standard_text=relevant_standard_text,
            future=future
        )

        async with self._lock:
            self._queue.append(task)
            # Start the batch processor if it's not running
            if self._batch_task is None or self._batch_task.done():
                 self._batch_task = asyncio.create_task(self._process_batches())

        # Auto-disable batching if queue is very small after a brief yield
        await asyncio.sleep(0.005) 
        async with self._lock:
            # If there's only 1 item and no others arrived, just process it immediately to save latency
            if len(self._queue) == 1 and self._queue[0] == task:
                self._queue.remove(task)
                # Process immediately outside the batch lock
                result = await self._run_single(task)
                future.set_result(result)
                return await future

        return await future

    async def _process_batches(self):
        """Background task that waits for the window or batch size, then flushes."""
        try:
            # Wait for the micro-batch window
            await asyncio.sleep(self.max_wait_ms / 1000.0)
            
            async with self._lock:
                if not self._queue:
                    return
                # Take up to batch_size items
                batch = self._queue[:self.batch_size]
                self._queue = self._queue[self.batch_size:]

            if not batch:
                return

            print(f"[BatchService] Flushing batch of {len(batch)} tasks...")
            await self._run_batch(batch)

            # If there are still items in the queue, schedule the next processor immediately
            async with self._lock:
                 if self._queue:
                      self._batch_task = asyncio.create_task(self._process_batches())

        except Exception as e:
            print(f"[BatchService] Error in batch processor: {e}")
            # Ensure futures are resolved on error
            for task in getattr(self, '_current_batch', []): 
                 if not task.future.done():
                      task.future.set_result({"error": str(e)})

    async def _run_single(self, task: ValidationTask) -> Dict[str, Any]:
         print(f"[BatchService] Processing single task {task.task_id} (No batching delay)")
         # Call the specialized Stage-1 AI prompt
         return await ai_service.evaluate_stage1_fast(
             task.section_text, 
             task.global_context, 
             task.relevant_standard_text
         )

    async def _run_batch(self, batch: List[ValidationTask]):
        self._current_batch = batch
        # For now, since Ollama Python client doesn't explicitly support a single grouped prompt 
        # that easily separates out JSON responses per section without complex formatting, 
        # we will execute them concurrently which allows Ollama's internal batching (continuous batching) 
        # to process them together efficiently if it supports it, OR we format a multi-part prompt.
        
        # We'll use concurrent requests. Since they fire at the EXACT same time,
        # Ollama's internal engine (llama.cpp or similar) can batch the KV cache.
        tasks = [
            ai_service.evaluate_stage1_fast(
                t.section_text, t.global_context, t.relevant_standard_text
            ) for t in batch
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for idx, task in enumerate(batch):
            res = results[idx]
            if isinstance(res, Exception):
                task.future.set_result({"error": str(res)})
            else:
                task.future.set_result(res)

batch_validation_service = BatchValidationService()
