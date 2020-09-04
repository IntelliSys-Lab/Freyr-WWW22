object TestCall {
   def main(args: Array[String]) {
        delayed(time());
   }

   def time(): Long = {
     val currentTime = System.currentTimeMillis();
     println("Get time: " + currentTime)
     return currentTime
   }
   
   def delayed( t: => Long ) = {
      println("Inside delayed:")
      println("param is " + t)
      t
   }
}
