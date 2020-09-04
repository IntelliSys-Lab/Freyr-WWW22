import java.util.concurrent._
import java.util.concurrent.atomic._

class RoundRobin(
  schedulerId: Int,
  invokers: IndexedSeq[Int]
) {
  def publish() = {
    val invoker: Int = RoundRobin.schedule(invokers)
    println(s"$schedulerId publishing action to invoker $invoker")
  }
}

object RoundRobin {
  private val roundRobinIndex: AtomicInteger = new AtomicInteger(0)
  
  def schedule(
    invokers: IndexedSeq[Int]
  ): Int = {
    roundRobinIndex.getAndIncrement() % invokers.length
  }
}

class SchedulerThread(
  schedulerId: Int,
  invokers: IndexedSeq[Int],
  requestSize: Int
) extends Runnable {
  override def run {
    val scheduler: RoundRobin = new RoundRobin(schedulerId, invokers)
    for (i <- 0 until requestSize) {
      scheduler.publish()
    }
  }
}

object Main {
  def main(args: Array[String]) {
    val invokers: IndexedSeq[Int] = IndexedSeq[Int](0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    val schedulerSize = 2
    val requestSize = 20
    val threadPool: ExecutorService = Executors.newFixedThreadPool(schedulerSize)
    
    try {
      for(i <- 0 until schedulerSize){
        threadPool.execute(new SchedulerThread(i, invokers, requestSize/schedulerSize))
      }
    } finally {
      threadPool.shutdown()
    }
  }
}
