import scala.concurrent._
import scala.util._
import ExecutionContext.Implicits.global

object Test {

  def main(args: Array[String]): Unit = {
    val list: Array[Int] = Array[Int](0, 3, 5, -9, 11) 
    var max: Int = list(0)
    
    for (i <- 0 until list.length) {
      val current: Int = list(i)
      if (current < max) {
        max = current
      }
    }
    
    println(max)
  }
}

